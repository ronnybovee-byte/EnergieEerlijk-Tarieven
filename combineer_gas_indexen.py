#!/usr/bin/env python3
"""Combineer bestaande leveranciersrapporten zonder bronvalidatie te overschrijven.

Input: gas_indexen_leveranciers.json en gas_luminus_index.json.
Output: gas_indexen_gecombineerd.json. Fail closed; geen jaarprijs/publicatie.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

REF = {'ENGIE Flow Gas': (85.777, 'ZTPDAM (Heren)', 'ZTP DAM'),
       'OCTA+ Boost Flex Gas': (87.893, 'ZTP RLP M', 'ZTP RLP Maand')}

def read_json(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: JSON-hoofdstructuur moet een object zijn')
    return data

def close(a, b, tolerance=0.00051):
    return type(a) in (int, float) and abs(a-b) <= tolerance

def combine(leveranciers, luminus):
    result = {
        'schema_version': 1,
        'gegenereerd_op_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'GECOMBINEERDE_BRONGEGEVENS_GEEN_JAARPRIJSVALIDATIE',
        'voor_android_app': False,
        'geschikt_voor_automatische_jaarprijs': False,
        'bronnen': ['gas_indexen_leveranciers.json', 'gas_luminus_index.json'],
        'contracten': {}
    }
    contracts = leveranciers.get('contracten')
    if not isinstance(contracts, dict):
        contracts = {}
    for name, (expected, index, definition) in REF.items():
        src = contracts.get(name, {})
        valid = (isinstance(src, dict)
                 and src.get('status') == 'HISTORISCHE_INDEX_GEVONDEN'
                 and src.get('index') == index
                 and src.get('index_definitie') == definition
                 and src.get('laatste_volledige_maand') == '2026-10'
                 and close(src.get('waarde_eur_per_mwh'), expected)
                 and close(src.get('waarde_ct_per_kwh'), expected / 10, 0.000051)
                 and isinstance(src.get('bron_url'), str)
                 and src['bron_url'].startswith('https://'))
        result['contracten'][name] = {
            'status': 'HISTORISCHE_BRONWAARDE_GECONTROLEERD' if valid else 'BRONCONTROLE_MISLUKT',
            'index': index,
            'historische_indexmaand': '2026-10' if valid else None,
            'historische_waarde_eur_per_mwh': expected if valid else None,
            'geschatte_jaarparameter_eur_per_mwh': 89.2144 if valid and name == 'ENGIE Flow Gas' else None,
            'herkomst_jaarparameter': 'tariefkaart_november_2026' if valid and name == 'ENGIE Flow Gas' else None,
            'bron_url': src.get('bron_url') if valid else None,
            'jaarprognose_gevalideerd': False,
            'geschikt_voor_automatische_jaarprijs': False,
            'blokkades': ['Jaarprijs en contractvoorwaarden niet gevalideerd'] if valid else ['Historische brongegevens niet betrouwbaar bevestigd']
        }
    lvalid = (luminus.get('status') == 'INDEX_EN_FORWARD_UIT_PDF_GEVONDEN'
              and luminus.get('index') == 'TTF DAH M'
              and luminus.get('tariefmaand') == '2026-11'
              and luminus.get('historische_indexmaand') == '2026-10'
              and luminus.get('bronbewijs_consistent') is True
              and close(luminus.get('historische_waarde_eur_per_mwh'), 86.104)
              and close(luminus.get('geschatte_jaarparameter_eur_per_mwh'), 89.218)
              and isinstance(luminus.get('bron_url'), str)
              and luminus['bron_url'].startswith('https://www.luminus.be/'))
    result['contracten']['Luminus BasicFlex Online Gas'] = {
        'status': 'HISTORISCHE_EN_FORWARD_BRONWAARDEN_GECONTROLEERD' if lvalid else 'BRONCONTROLE_MISLUKT',
        'index': 'TTF DAH M',
        'historische_indexmaand': '2026-10' if lvalid else None,
        'historische_waarde_eur_per_mwh': 86.104 if lvalid else None,
        'geschatte_jaarparameter_eur_per_mwh': 89.218 if lvalid else None,
        'herkomst_jaarparameter': 'luminus_indexen_pdf_november_2026' if lvalid else None,
        'bron_url': luminus.get('bron_url') if lvalid else None,
        'jaarprognose_gevalideerd': False,
        'geschikt_voor_automatische_jaarprijs': False,
        'blokkades': ['Jaarprijs en contractvoorwaarden niet gevalideerd'] if lvalid else ['Luminus brongegevens niet betrouwbaar bevestigd']
    }
    result['alle_broncontroles_geslaagd'] = all(x['status'] != 'BRONCONTROLE_MISLUKT' for x in result['contracten'].values())
    result['waarschuwing'] = 'Vastgepinde controles voor november 2026; toekomstige maanden vereisen een nieuwe validatieregel.'
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--leveranciers', default='gas_indexen_leveranciers.json')
    parser.add_argument('--luminus', default='gas_luminus_index.json')
    parser.add_argument('--output', default='gas_indexen_gecombineerd.json')
    args = parser.parse_args()
    try:
        result = combine(read_json(args.leveranciers), read_json(args.luminus))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {'schema_version': 1, 'status': 'BRONBESTAND_ONLEESBAAR',
                  'voor_android_app': False, 'geschikt_voor_automatische_jaarprijs': False,
                  'reden': f'{type(exc).__name__}: {exc}', 'contracten': {}}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(result['status'])
    for name, contract in result['contracten'].items():
        print(f"{name}: {contract['status']}")

if __name__ == '__main__':
    main()
