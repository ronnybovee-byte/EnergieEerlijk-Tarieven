#!/usr/bin/env python3
"""Controleer gevonden gasarchief-PDF's zonder gevalideerde formules te wijzigen.

Leest gas_gevonden_tariefkaarten.json en gas_gevalideerde_formules.json.
Schrijft uitsluitend gas_archief_validatie.json. Vereist requests en pymupdf.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
import fitz

INVOER = Path('gas_gevonden_tariefkaarten.json')
FORMULES = Path('gas_gevalideerde_formules.json')
UITVOER = Path('gas_archief_validatie.json')


def lees_json(pad):
    return json.loads(pad.read_text(encoding='utf-8'))


def controleer_pdf(url, maand, sessie):
    resultaat = {'pdf_url': url, 'tariefmaand_archief': maand, 'status': 'niet_gevalideerd'}
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be':
        resultaat['reden'] = 'onverwacht_domein'
        return resultaat
    expected_hash = parse_qs(parsed.query).get('pdf', [''])[0].lower()
    if not re.fullmatch(r'[a-f0-9]{64}', expected_hash):
        resultaat['reden'] = 'ongeldige_archiefidentificatie'
        return resultaat
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', str(maand)):
        resultaat['reden'] = 'ongeldige_archiefmaand'
        return resultaat
    try:
        response = sessie.get(url, timeout=40)
        response.raise_for_status()
        data = response.content
        if not data.startswith(b'%PDF-'):
            raise ValueError('download is geen PDF')
        if len(data) > 15_000_000:
            raise ValueError('PDF te groot')
        sha = hashlib.sha256(data).hexdigest()
        resultaat['sha256'] = sha
        resultaat['pdf_bytes'] = len(data)
        resultaat['hash_komt_overeen'] = sha == expected_hash
        with fitz.open(stream=data, filetype='pdf') as doc:
            tekst = '\n'.join(doc[i].get_text() for i in range(min(len(doc), 12)))
        jaar, maandnummer = maand.split('-')
        maandnamen = ['januari', 'februari', 'maart', 'april', 'mei', 'juni',
                      'juli', 'augustus', 'september', 'oktober', 'november', 'december']
        maandnaam = maandnamen[int(maandnummer) - 1]
        resultaat['maand_vermeld_in_pdf'] = bool(re.search(
            rf'\b{maandnaam}\s+{jaar}\b|\b{maandnummer}[/-]{jaar}\b',
            tekst, re.IGNORECASE))
        resultaat['status'] = ('pdf_technisch_gecontroleerd' if resultaat['hash_komt_overeen']
                               else 'hash_afwijking')
        resultaat['reden'] = ('PDF bereikbaar; maandvermelding is slechts indicatief, '
                              'prijsformule en contractidentiteit niet gevalideerd')
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        resultaat['status'] = 'controle_mislukt'
        resultaat['reden'] = str(exc)[:250]
    return resultaat


def main():
    bron = lees_json(INVOER)
    gevalideerd = lees_json(FORMULES)
    bekende = gevalideerd.get('contracten', {})
    uitvoer = {
        'schema_version': 1,
        'gecontroleerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'alleen_technische_pdf_controle',
        'waarschuwing': 'Geen prijs-, formule-, index- of contractvalidatie. Niets automatisch publiceren.',
        'contracten': {},
    }
    with requests.Session() as sessie:
        sessie.headers.update({'User-Agent': 'EerlijkeEnergie-GasArchiefControle/1.0'})
        for naam, info in bron.get('contracten', {}).items():
            if naam not in bekende:
                uitvoer['contracten'][naam] = {'status': 'onbekend_contract'}
                print(f'{naam}: onbekend contract, overgeslagen')
                continue
            kandidaten = info.get('kandidaten', [])
            if not kandidaten:
                uitvoer['contracten'][naam] = {'status': 'geen_kandidaten'}
                print(f'{naam}: geen kandidaten')
                continue
            nieuwste = max(kandidaten, key=lambda k: k.get('tariefmaand_archief', ''))
            resultaat = controleer_pdf(nieuwste.get('pdf_url', ''),
                                       nieuwste.get('tariefmaand_archief', ''), sessie)
            uitvoer['contracten'][naam] = resultaat
            print(f"{naam}: {resultaat['status']}; maand={resultaat['tariefmaand_archief']}; "
                  f"maand_vermeld={resultaat.get('maand_vermeld_in_pdf', 'onbekend')}")
    tijdelijk = UITVOER.with_suffix('.json.tmp')
    tijdelijk.write_text(json.dumps(uitvoer, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tijdelijk.replace(UITVOER)
    print(f'Rapport geschreven: {UITVOER}')


if __name__ == '__main__':
    main()
