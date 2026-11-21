#!/usr/bin/env python3
"""Combineer bestaande leveranciersrapporten zonder bronvalidatie te overschrijven.

Input: gas_indexen_leveranciers.json en gas_luminus_index.json.
Output: gas_indexen_gecombineerd.json. Fail closed; geen jaarprijs/publicatie.
"""
import argparse
import datetime as dt
import json
import math
import re
from haal_engie_gasindex_op import MONTHS
from pathlib import Path

REF = {
    'ENGIE Flow Gas': ('ZTPDAM (Heren)', 'ZTP DAM'),
    'OCTA+ Boost Flex Gas': ('ZTP RLP M', 'ZTP RLP Maand')
}

def read_json(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: JSON-hoofdstructuur moet een object zijn')
    return data

def close(a, b, tolerance=0.00051):
    return type(a) in (int, float) and abs(a-b) <= tolerance

def combine(leveranciers, luminus, current=None, genormaliseerd=None):
    current = current or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m')
    vorige_maand = (dt.date.fromisoformat(current + '-01') - dt.timedelta(days=1)).strftime('%Y-%m')
    result = {
        'schema_version': 1,
        'gegenereerd_op_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'GECOMBINEERDE_BRONGEGEVENS_GEEN_JAARPRIJSVALIDATIE',
        'voor_android_app': False,
        'geschikt_voor_automatische_jaarprijs': False,
        'bronnen': ['gas_indexen_leveranciers.json', 'gas_luminus_index.json', 'gas_indexwaarden_bewijs.json'],
        'contracten': {}
    }
    contracts = leveranciers.get('contracten')
    if not isinstance(contracts, dict):
        contracts = {}
    for name, (index, definition) in REF.items():
        src = contracts.get(name, {})
        valid = (isinstance(src, dict)
                 and src.get('status') == 'HISTORISCHE_INDEX_GEVONDEN'
                 and src.get('index') == index
                 and src.get('index_definitie') == definition
                 and isinstance(src.get('laatste_volledige_maand'), str)
                 and len(src['laatste_volledige_maand']) == 7
                 and src['laatste_volledige_maand'] == vorige_maand
                 and type(src.get('waarde_eur_per_mwh')) in (int, float)
                 and math.isfinite(src['waarde_eur_per_mwh'])
                 and 0 < src['waarde_eur_per_mwh'] <= 1000
                 and close(src.get('waarde_ct_per_kwh'), src.get('waarde_eur_per_mwh', -999) / 10, 0.000051)
                 and isinstance(src.get('bron_url'), str)
                 and src['bron_url'].startswith('https://'))
        norm = genormaliseerd or {}
        n = norm.get('contracten', {}).get(name, {})
        forward = n.get('geschatte_jaarparameter_eur_per_mwh')
        historische_waarden = set()

        for regel in n.get('index_bronregels', []):
            tekst = regel.get('tekst', '')

            patroon = (
                r'laatst gekende waarde van\s+'
                r'ZTPDAM\s*\(Heren\)\s*\('
                r'([a-z]+)\s+(20\d{2}):\s*'
                r'(\d{1,3}[,.]\d{1,4})'
            )

            for match in re.finditer(patroon, tekst, re.I):
                maandnummer = MONTHS.get(match.group(1).lower())

                if maandnummer:
                    maand = f'{match.group(2)}-{maandnummer:02d}'
                    waarde = float(match.group(3).replace(',', '.'))
                    historische_waarden.add((maand, waarde))
       
        # Bij een mislukte websitecontrole: actuele ENGIE-tariefkaart.
        if (
            name == 'ENGIE Flow Gas'
            and not valid
            and norm.get('schema_version') == 1
            and n.get('tariefmaand') == current
            and n.get('status') == 'BRONREGELS_GEVONDEN_HANDMATIGE_CONTROLE'
            and re.fullmatch(r'[a-f0-9]{64}', n.get('pdf_sha256') or '')
            and len(historische_waarden) == 1
        ):
            maand, waarde = next(iter(historische_waarden))
            if maand == vorige_maand and 0 < waarde <= 1000:
                src = {
                    'laatste_volledige_maand': maand,
                    'waarde_eur_per_mwh': waarde,
                    'bron_url': 'https://energieplatform-vlaanderen.be/tariefkaartarchief?pdf=' + n['pdf_sha256'],
                }
                valid = True
        historisch_ok = (
            len(historische_waarden) == 1
            and all(
                maand == vorige_maand
                and close(waarde, src.get('waarde_eur_per_mwh', -999))
                for maand, waarde in historische_waarden
            )
        )
        eforward = (
            name == 'ENGIE Flow Gas'
            and valid
            and norm.get('schema_version') == 1
            and n.get('tariefmaand') == current
            and historisch_ok
            and n.get('status') == 'BRONREGELS_GEVONDEN_HANDMATIGE_CONTROLE'
            and src.get('laatste_volledige_maand') == vorige_maand
            and type(forward) in (int, float)
            and math.isfinite(forward)
            and 0 < forward <= 1000
        )
        evidence = {'bron': 'gas_indexwaarden_bewijs.json',
                    'tariefmaand': current, 'bronbewijs_consistent': True} if eforward else None

        if name == 'OCTA+ Boost Flex Gas':
            forward = src.get(
                'geschatte_jaarparameter_eur_per_mwh'
            )

            eforward = (
                valid
                and src.get('jaarprognose_gevalideerd') is True
                and src.get('jaarparameter_tariefmaand') == current
                and src.get('laatste_volledige_maand') == vorige_maand
                and src.get('jaarparameter_bron_url') ==
                    'https://files.octaplus.be/tariffs/parameters_forward_nl.pdf'
                and type(forward) in (int, float)
                and math.isfinite(forward)
                and forward > 0
            )

            evidence = {
                'bron': src.get('jaarparameter_bron_url'),
                'tariefmaand': current,
                'bronbewijs_consistent': True
            } if eforward else None
        result['contracten'][name] = {
            'status': 'HISTORISCHE_EN_FORWARD_BRONWAARDEN_GECONTROLEERD' if eforward else ('HISTORISCHE_BRONWAARDE_GECONTROLEERD' if valid else 'BRONCONTROLE_MISLUKT'),
            'index': index,
            'historische_indexmaand': src.get('laatste_volledige_maand') if valid else None,
            'historische_waarde_eur_per_mwh': src.get('waarde_eur_per_mwh') if valid else None,
            'geschatte_jaarparameter_eur_per_mwh': forward if eforward else None,
            'herkomst_jaarparameter': (
                evidence['bron'] if eforward else None
            ),
            'bron_url': src.get('bron_url') if valid else None,
            'jaarprognose_gevalideerd': eforward,
            'jaarparameter_bronbewijs': evidence if eforward else None,
            'geschikt_voor_automatische_jaarprijs': False,
            'blokkades': [] if eforward else (['Jaarprognose niet gevalideerd'] if valid else ['Historische brongegevens niet betrouwbaar bevestigd'])
        }
    lvalid = (luminus.get('status') == 'INDEX_EN_FORWARD_UIT_PDF_GEVONDEN'
              and luminus.get('index') == 'TTF DAH M'
              and luminus.get('tariefmaand') == current
              and isinstance(luminus.get('historische_indexmaand'), str)
              and luminus.get('historische_indexmaand') == (dt.date.fromisoformat(luminus['tariefmaand'] + '-01') - dt.timedelta(days=1)).strftime('%Y-%m')
              and luminus.get('bronbewijs_consistent') is True
              and type(luminus.get('historische_waarde_eur_per_mwh')) in (int, float)
              and type(luminus.get('geschatte_jaarparameter_eur_per_mwh')) in (int, float)
              and 1 <= luminus['historische_waarde_eur_per_mwh'] <= 1000
              and 1 <= luminus['geschatte_jaarparameter_eur_per_mwh'] <= 1000
              and isinstance(luminus.get('bron_url'), str)
              and luminus['bron_url'].startswith('https://www.luminus.be/'))
    lforward = (lvalid and luminus['tariefmaand'] == current
                and luminus['historische_indexmaand'] == vorige_maand)
    result['contracten']['Luminus BasicFlex Online Gas'] = {
        'status': 'HISTORISCHE_EN_FORWARD_BRONWAARDEN_GECONTROLEERD' if lvalid else 'BRONCONTROLE_MISLUKT',
        'index': 'TTF DAH M',
        'historische_indexmaand': luminus.get('historische_indexmaand') if lvalid else None,
        'historische_waarde_eur_per_mwh': luminus.get('historische_waarde_eur_per_mwh') if lvalid else None,
        'geschatte_jaarparameter_eur_per_mwh': luminus.get('geschatte_jaarparameter_eur_per_mwh') if lvalid else None,
        'herkomst_jaarparameter': 'luminus_indexen_pdf_' + luminus['tariefmaand'] if lvalid else None,
        'bron_url': luminus.get('bron_url') if lvalid else None,
        'jaarprognose_gevalideerd': lforward,
        'geschikt_voor_automatische_jaarprijs': False,
        'blokkades': ([] if lforward else ['Jaarparameter niet actueel']) if lvalid else ['Luminus brongegevens niet betrouwbaar bevestigd']
    }
    for c in result['contracten'].values():
        c['actueel_voor_huidige_maand'] = (
            c['historische_indexmaand'] == vorige_maand
            and c['jaarprognose_gevalideerd'] is True
        )

    result['alle_broncontroles_geslaagd'] = all(
        c['status'] != 'BRONCONTROLE_MISLUKT'
        for c in result['contracten'].values()
    )

    result['huidige_kalendermaand_utc'] = current

    result['actueel_voor_huidige_maand'] = all(
        c['actueel_voor_huidige_maand']
        for c in result['contracten'].values()
    )

    if not result['actueel_voor_huidige_maand']:
        result['status'] = 'GEDEELTELIJKE_OF_ONVOLLEDIGE_BRONGEGEVENS'
    # Volledige contractvrijgave blijft de taak van controle_gas_publicatie.py.
    result['waarschuwing'] = 'Bronindexen zijn geen volledige jaarprijzen; tariefkaarten en kosten moeten afzonderlijk worden gevalideerd.'
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--leveranciers', default='gas_indexen_leveranciers.json')
    parser.add_argument('--luminus', default='gas_luminus_index.json')
    parser.add_argument('--genormaliseerd', default='gas_indexwaarden_bewijs.json')
    parser.add_argument('--output', default='gas_indexen_gecombineerd.json')
    args = parser.parse_args()
    try:
        try:
            norm = read_json(args.genormaliseerd)
        except (OSError, ValueError):
            norm = {}

        try:
            leveranciers = read_json(args.leveranciers)
        except (OSError, ValueError):
            leveranciers = {}

        try:
            luminus = read_json(args.luminus)
        except (OSError, ValueError):
            luminus = {}

        result = combine(
            leveranciers,
            luminus,
            genormaliseerd=norm
        )
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
