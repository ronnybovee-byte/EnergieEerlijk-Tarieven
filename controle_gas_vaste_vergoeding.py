#!/usr/bin/env python3
"""Onderzoeksrapport vaste gasvergoeding uit de reeds gecontroleerde archief-PDF's.

GEEN automatische tariefgoedkeuring; geen aanpassing aan Android of bronformules.
Draai na controle_gas_archiefformules.py in dezelfde GitHub Actions job.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from controle_gas_tariefkaarten import lees_pdf

SOURCE = Path('gas_archiefformules_vergelijking.json')
OUTPUT = Path('gas_vaste_vergoeding_kandidaten.json')
KEYWORDS = re.compile(r'(?:vaste\s+(?:vergoeding|kosten|bijdrage)|jaarlijkse\s+(?:vergoeding|bijdrage)|abonnement|forfait|vaste\s+retributie)', re.I)
AMOUNT = re.compile(r'(?<!\d)(?:\d{1,4}(?:[.,]\d{1,4})?)\s*(?:€|EUR|euro|€/jaar|€/maand)', re.I)


def zoek_kandidaten(tekst):
    """Geef broncitaten, niet automatisch geïnterpreteerde bedragen."""
    regels = [re.sub(r'\s+', ' ', r).strip() for r in tekst.splitlines()]
    matches = []
    for i, regel in enumerate(regels):
        if not KEYWORDS.search(regel):
            continue
        context = ' | '.join(r for r in regels[max(0, i-1):min(len(regels), i+3)] if r)
        matches.append({'regel': i+1, 'tekst': context[:500],
                        'bedrag_herkend_in_context': bool(AMOUNT.search(context))})
    return matches[:35]


def controleer(naam, info, sessie):
    result = {'status': 'handmatige_controle_nodig', 'vaste_vergoeding_gevalideerd': False,
              'tariefmaand': info.get('tariefmaand_archief'), 'pdf_url': info.get('pdf_url'),
              'kandidaten': []}
    if info.get('status') != 'formule_gelijk_aan_referentie' or info.get('formule_gelijk') is not True:
        result['reden'] = 'formulevergelijking_niet_geslaagd'
        return result
    url = info.get('pdf_url')
    if not isinstance(url, str):
        result['reden'] = 'ontbrekende_url'
        return result
    parsed = urlparse(url)
    sha = parse_qs(parsed.query).get('pdf', [''])[0].lower()
    if parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be' or not re.fullmatch(r'[a-f0-9]{64}', sha):
        result['reden'] = 'onbetrouwbare_pdf_url'
        return result
    try:
        response = sessie.get(url, timeout=45)
        response.raise_for_status()
        pdf = response.content
        if len(pdf) > 15_000_000 or not pdf.startswith(b'%PDF-'):
            raise ValueError('geen_geldige_pdf')
        digest = hashlib.sha256(pdf).hexdigest()
        if digest != sha or digest != info.get('sha256'):
            raise ValueError('pdf_hash_verschilt')
        tekst, ocr = lees_pdf(pdf)
        result['pdf_sha256'] = digest
        result['ocr_paginas'] = ocr
        result['kandidaten'] = zoek_kandidaten(tekst)
        result['reden'] = ('kandidaatregels_gevonden_maandbedrag_en_btw_nog_te_controleren'
                           if result['kandidaten'] else 'geen_herkenbare_vergoedingsregels')
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        result['reden'] = 'pdf_controle_mislukt: ' + str(exc)[:180]
    return result


def main():
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    if source.get('schema_version') != 1 or not isinstance(source.get('contracten'), dict):
        raise SystemExit('Ongeldig bronrapport')
    output = {'schema_version': 1, 'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'KANDIDATEN_GEEN_GEVERIFIEERDE_VASTE_VERGOEDING',
              'voor_android_app': False,
              'waarschuwing': 'Bedragen, periode, btw, kortingen en voorwaarden vereisen aparte controle.',
              'contracten': {}}
    with requests.Session() as sessie:
        sessie.headers.update({'User-Agent': 'EerlijkeEnergie-GasVasteVergoedingControle/1.0'})
        for naam, info in source['contracten'].items():
            output['contracten'][naam] = controleer(naam, info, sessie)
            print(naam, ':', output['contracten'][naam]['reden'])
    tmp = OUTPUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(output, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    tmp.replace(OUTPUT)
    print('Rapport:', OUTPUT)


if __name__ == '__main__':
    main()
