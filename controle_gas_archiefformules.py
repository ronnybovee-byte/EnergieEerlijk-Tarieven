#!/usr/bin/env python3
"""Vergelijk nieuwste gasarchief-PDF's met gevalideerde formules (alleen rapport).

Geen aanpassing aan bestaande formules, bronregister of Android-bestanden.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from controle_gas_tariefkaarten import GAS_CONTRACTEN, herken_formule, lees_pdf, normaliseer_index, valideer_formule

KANDIDATEN = Path('gas_gevonden_tariefkaarten.json')

UITVOER = Path('gas_archiefformules_vergelijking.json')
MAANDNAMEN = ('januari', 'februari', 'maart', 'april', 'mei', 'juni',
              'juli', 'augustus', 'september', 'oktober', 'november', 'december')


def vergelijk(naam, kandidaat, referentie, sessie):
    resultaat = {
        'tariefmaand_archief': kandidaat.get('tariefmaand_archief'),
        'pdf_url': kandidaat.get('pdf_url'),
        'status': 'handmatige_controle_nodig',
    }
    url = resultaat['pdf_url']
    maand = resultaat['tariefmaand_archief']
    if not isinstance(url, str) or not isinstance(maand, str):
        resultaat['reden'] = 'ontbrekende_url_of_maand'
        return resultaat
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be':
        resultaat['reden'] = 'onverwachte_bron'
        return resultaat
    hash_id = parse_qs(parsed.query).get('pdf', [''])[0].lower()
    if not re.fullmatch(r'[0-9a-f]{64}', hash_id):
        resultaat['reden'] = 'ongeldige_pdf_identificatie'
        return resultaat
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', maand):
        resultaat['reden'] = 'ongeldige_maand'
        return resultaat
    try:
        response = sessie.get(url, timeout=45)
        response.raise_for_status()
        pdf = response.content
        if not pdf.startswith(b'%PDF-') or len(pdf) > 15_000_000:
            raise ValueError('geen_geldige_pdf_of_te_groot')
        sha = hashlib.sha256(pdf).hexdigest()
        resultaat['sha256'] = sha
        if sha != hash_id:
            resultaat['reden'] = 'sha256_verschilt_van_archief_id'
            return resultaat
        huidige_maand = datetime.now(timezone.utc).strftime('%Y-%m')
        if maand != huidige_maand:
            resultaat['reden'] = 'geen_actuele_tariefkaart'
            return resultaat

        tekst, ocr_paginas = lees_pdf(pdf)
        resultaat['ocr_paginas'] = ocr_paginas
        if not tekst.strip():
            resultaat['reden'] = 'geen_leesbare_tekst'
            return resultaat
        woorden = GAS_CONTRACTEN[naam].get('vereiste_woorden', [])
        if naam == 'Ecofix Flexy Online':
            woorden = ['Ecofix', 'Flexy Online']
        ontbrekend = [w for w in woorden if w.casefold() not in tekst.casefold()]
        resultaat['contract_herkend'] = not ontbrekend
        if ontbrekend:
            resultaat['reden'] = 'contractnaam_of_kenmerk_ontbreekt: ' + ', '.join(ontbrekend)
            return resultaat
        jaar, mm = maand.split('-')
        maandnaam = MAANDNAMEN[int(mm)-1]
        resultaat['maand_vermeld'] = bool(re.search(
            rf'\b{maandnaam}\s+{jaar}\b|\b{mm}[/-]{jaar}\b', tekst, re.IGNORECASE))
        if not resultaat['maand_vermeld']:
            resultaat['reden'] = 'archiefmaand_niet_in_pdf_gevonden'
            return resultaat
        gevonden = herken_formule(tekst)
        resultaat['formule_gevonden'] = gevonden
        if gevonden is None:
            resultaat['reden'] = 'formule_niet_herkend'
            return resultaat
        if not valideer_formule(
            gevonden, GAS_CONTRACTEN[naam]['verwachte_formule']['index']
        ):
            resultaat['reden'] = 'ongeldige_formule_of_onbekende_index'
            return resultaat
        verwacht = {k: referentie[k] for k in ('index', 'factor', 'toeslag')}
        resultaat['referentieformule'] = verwacht
        gelijk = (normaliseer_index(gevonden['index']) == normaliseer_index(verwacht['index'])
                  and abs(float(gevonden['factor'])-float(verwacht['factor'])) < 0.000001
                  and abs(float(gevonden['toeslag'])-float(verwacht['toeslag'])) < 0.000001)
        resultaat['formule_gelijk'] = gelijk
        resultaat['formule_technisch_gevalideerd'] = True
        resultaat['coefficienten_gewijzigd'] = not gelijk
        resultaat['referentie_index_behouden'] = True
        resultaat['index_eenheid_verwacht'] = GAS_CONTRACTEN[naam]['index_eenheid']
        resultaat['formule_uitkomst_eenheid_verwacht'] = GAS_CONTRACTEN[naam]['formule_uitkomst_eenheid']
        resultaat['formule_eenheden_gevalideerd'] = False 
        tekst_norm = re.sub(r'\s+', ' ', tekst).casefold()
        resultaat['index_eenheid_gevalideerd'] = False

        if naam == 'ENGIE Flow Gas':
            resultaat['index_eenheid_gevalideerd'] = bool(re.search(
                r'de geschatte jaarlijkse parameter\s+ztpdam\s*\(heren\)\s+bedraagt.{0,180}?\d+[,.]\d+\s*€/mwh',
                tekst_norm
            ))

        elif naam == 'Luminus BasicFlex Online Gas':
            resultaat['index_eenheid_gevalideerd'] = bool(re.search(
                r'ttf\s+dah\s+m\s*=\s*\d+[,.]\d+\s*€/mwh',
                tekst_norm
            ))
         if (
            naam in ('ENGIE Flow Gas', 'Luminus BasicFlex Online Gas')
            and resultaat['index_eenheid_gevalideerd']
        ):
            resultaat['index_omrekenfactor'] = 1.0       
      if naam == 'OCTA+ Boost Flex Gas':
            uitkomst_bevestigd = bool(re.search(
                r'prijsformule\s+is\s+als\s+volgt,\s+in\s+ceur/kwh\s+excl\.\s*btw',
                tekst_norm
            ))

            omrekening_bevestigd = bool(re.search(
                r'eur/mwh,\s+volstaat\s+het\s+om\s+de\s+waarde\s+te\s+delen\s+door\s+10\s+voor\s+de\s+toepassing\s+van\s+de\s+prijsindexatieformule\s+in\s+ceur/kwh',
                tekst_norm
            ))

            resultaat['formule_eenheden_gevalideerd'] = (
                uitkomst_bevestigd and omrekening_bevestigd
            )

            if resultaat['formule_eenheden_gevalideerd']:
                resultaat['index_omrekenfactor'] = 0.1     
                resultaat['index_eenheid_gevalideerd'] = True              
        resultaat['formule_bronregels'] = [
            regel.strip()
            for regel in tekst.splitlines()
            if re.search(
                r'tariefformule|prijsformule|€/MWh|EUR/MWh|c€/kWh|cent/kWh',
                regel,
                re.IGNORECASE
            )
        ][:80]      
        resultaat['status'] = 'formule_gelijk_aan_referentie' if gelijk else 'formule_afwijkend'
        resultaat['reden'] = ('Formulevergelijking geslaagd; geen controle van indexwaarde, '
                              'indexeenheid, vaste vergoeding of jaarprijs' if gelijk else
                              'Afwijking in index, factor of toeslag; handmatige beoordeling vereist')
    except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as exc:
        resultaat['reden'] = f'controle_mislukt: {str(exc)[:220]}'
    return resultaat


def main():
    bron = json.loads(KANDIDATEN.read_text(encoding='utf-8'))
    referenties = {
        naam: gegevens['verwachte_formule']
        for naam, gegevens in GAS_CONTRACTEN.items()
    }
    rapport = {
        'schema_version': 1,
        'gecontroleerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'alleen_formulevergelijking_niet_voor_app',
        'waarschuwing': 'Geen automatische publicatie of goedkeuring van volledige gasprijzen.',
        'contracten': {},
    }
    with requests.Session() as sessie:
        sessie.headers.update({'User-Agent': 'EerlijkeEnergie-GasFormuleControle/1.0'})
        for naam, info in bron.get('contracten', {}).items():
            if naam not in referenties or naam not in GAS_CONTRACTEN:
                rapport['contracten'][naam] = {'status': 'onbekend_contract'}
            elif not info.get('kandidaten'):
                rapport['contracten'][naam] = {'status': 'geen_kandidaten'}
            else:
                kandidaat = max(info['kandidaten'], key=lambda x: x.get('tariefmaand_archief', ''))
                rapport['contracten'][naam] = vergelijk(naam, kandidaat, referenties[naam], sessie)
            print(f"{naam}: {rapport['contracten'][naam]['status']}")
    tijdelijk = UITVOER.with_name(UITVOER.name + '.tmp')
    tijdelijk.write_text(json.dumps(rapport, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tijdelijk.replace(UITVOER)
    print(f'Rapport geschreven: {UITVOER}')
    print('Bestaande gevalideerde formules niet gewijzigd.')


if __name__ == '__main__':
    main()
