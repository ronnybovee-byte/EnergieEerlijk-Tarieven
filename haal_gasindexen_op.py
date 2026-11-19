#!/usr/bin/env python3
"""Conservatieve broncollector: OCTA+ ZTP RLP Maand; geen jaarprognoses."""
import datetime as dt
import io
import json
import re
from pathlib import Path

import pdfplumber
import requests

URL = 'https://files.octaplus.be/tariffs/parameters_aardgas_nl.pdf'
OUT = Path('gas_indexen_leveranciers.json')


def collect_octaplus():
    response = requests.get(URL, timeout=35, headers={'User-Agent': 'EerlijkeEnergie/1.0 (tariefcontrole)'})
    response.raise_for_status()
    if not response.content.startswith(b'%PDF'):
        raise ValueError('Bron is geen PDF')
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        lines = '\n'.join((p.extract_text(layout=False) or '') for p in pdf.pages).splitlines()
    heading = next((line for line in lines if 'ZTP RLP Mois' in line and 'Periode' in line), None)
    if not heading:
        raise ValueError('Verwachte kolomkop ZTP RLP Mois ontbreekt')
    headers = re.split(r'\s{2,}', heading.strip())
    # pdfplumber can collapse spacing; the known published table has five numerical columns.
    if 'ZTP RLP Mois' not in heading or 'TTF RLP Mois' not in heading:
        raise ValueError('Kolomindeling niet herkenbaar')
    found = {}
    for line in lines:
        match = re.match(r'^\s*(\d{2})/(\d{4})\s+(.+)$', line)
        if not match:
            continue
        month, year, tail = match.groups()
        date = f'{year}-{month}'
        values = tail.split()
        # Only accept rows with all five columns, never guess a missing ZTP RLP value.
        if len(values) != 5 or not all(re.fullmatch(r'\d+(?:[,.]\d+)?', v) for v in values):
            continue
        value = float(values[3].replace(',', '.'))
        if not (1 <= value <= 1000):
            continue
        found[date] = value
    if not found:
        raise ValueError('Geen volledige rijen met ZTP RLP Maand gevonden')
    last = max(found)
    if last > dt.datetime.now(dt.timezone.utc).strftime('%Y-%m'):
        raise ValueError('Toekomstige indexmaand gevonden')
    return {'status': 'HISTORISCHE_INDEX_GEVONDEN', 'bron_url': URL,
            'index': 'ZTP RLP M', 'index_definitie': 'ZTP RLP Maand',
            'laatste_volledige_maand': last,
            'waarde_eur_per_mwh': found[last],
            'waarde_ct_per_kwh': round(found[last] / 10, 6),
            'aantal_historische_maanden': len(found),
            'jaarprognose_gevalideerd': False,
            'geschikt_voor_automatische_jaarprijs': False}


def main():
    report = {'schema_version': 1,
              'gegenereerd_op_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'voor_android_app': False,
              'status': 'HISTORISCHE_BRONCONTROLE_GEEN_JAARPRIJS',
              'contracten': {
                  'ENGIE Flow Gas': {'status': 'BRONADAPTER_NOG_NIET_GEVALIDEERD'},
                  'Luminus BasicFlex Online Gas': {'status': 'BRONADAPTER_NOG_NIET_GEVALIDEERD'},
                  'OCTA+ Boost Flex Gas': {'status': 'BRON_NIET_BEREIKBAAR_OF_FORMAAT_ONBEKEND'}
              }}
    try:
        report['contracten']['OCTA+ Boost Flex Gas'] = collect_octaplus()
    except (requests.RequestException, ValueError, Exception) as exc:
        report['contracten']['OCTA+ Boost Flex Gas']['fout'] = f'{type(exc).__name__}: {str(exc)[:300]}'
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Rapport:', OUT)
    for name, value in report['contracten'].items():
        print(name, ':', value['status'])


if __name__ == '__main__':
    main()
