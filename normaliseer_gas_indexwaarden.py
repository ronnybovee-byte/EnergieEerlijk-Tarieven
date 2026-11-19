#!/usr/bin/env python3
"""Normaliseer gecontroleerd PDF-bronbewijs; nooit automatische jaarprijsgoedkeuring."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

BRON = Path('gas_indexwaarden_bewijs.json')
UITVOER = Path('gas_indexwaarden_genormaliseerd.json')
MAAND = '2026-11'
# Strikte, maandspecifieke bewijssjablonen: nieuwe kaarten vereisen herbeoordeling.
SPEC = {
    'ENGIE Flow Gas': {
        'sha256': 'dc12088e63cec5de4e893c6ed2003903804ad794b2b31d08257f3e30ce222da1',
        'index': 'ZTPDAM (Heren)', 'historisch': '85,7770', 'jaar': '89,2144',
        'formule_index': 'ZTPDAM(HEREN)', 'factor': 0.102, 'toeslag': 1.0095,
    },
    'Luminus BasicFlex Online Gas': {
        'sha256': 'd1105da725c750ad6570110124ad0eab588d12f27706107efadf84453d467b65',
        'index': 'TTF DAH M', 'historisch': '86,104', 'jaar': None,
        'formule_index': 'TTFDAHM', 'factor': 0.1001, 'toeslag': 0.5279,
    },
    'OCTA+ Boost Flex Gas': {
        'sha256': '432590afb3a59d20b4f0050ce67166b7b576aed062da530bcb838a4e49b1e9b0',
        'index': 'ZTP RLP M', 'historisch': None, 'jaar': None,
        'formule_index': 'ZTPRLPM', 'factor': 1.02, 'toeslag': 0.32,
    },
}


def alle_teksten(item):
    return '\n'.join(str(r.get('tekst', '')) for veld in ('index_bronregels', 'waarde_bronregels')
                     for r in item.get(veld, []) if isinstance(r, dict))


def bevat_waarde(tekst, waarde):
    # De waarde moet expliciet gekoppeld zijn aan €/MWh, niet aan een willekeurig getal.
    return bool(re.search(r'(?<![\d,])' + re.escape(waarde) +
                          r'\s*(?:€|EUR)\s*/\s*MWh\b', tekst, re.I))


def controleer(naam, item, spec):
    blokkades = []
    if item.get('tariefmaand') != MAAND:
        blokkades.append('Tariefmaand verschilt')
    if item.get('pdf_sha256') != spec['sha256']:
        blokkades.append('PDF-hash verschilt')
    if item.get('status') != 'BRONREGELS_GEVONDEN_HANDMATIGE_CONTROLE':
        blokkades.append('Geen bruikbaar PDF-bronbewijs')
    formule = item.get('formule_uit_archief') or {}
    if (formule.get('index') != spec['formule_index'] or
        formule.get('factor') != spec['factor'] or
        formule.get('toeslag') != spec['toeslag']):
        blokkades.append('Formule wijkt af van referentie')
    tekst = alle_teksten(item)
    if not re.search(re.escape(spec['index']).replace(r'\ ', r'\s*'), tekst, re.I):
        blokkades.append('Indexnaam niet teruggevonden')
    historisch = spec['historisch']
    jaar = spec['jaar']
    if historisch and (not (bevat_waarde(tekst, historisch) or (naam == 'ENGIE Flow Gas' and re.search(r'oktober\s+2026\s*:\s*85,7770', tekst, re.I) and '€/MWh' in tekst)) or 'oktober 2026' not in tekst.lower()):
        blokkades.append('Historische indexwaarde of maand niet bewezen')
    if jaar and (not bevat_waarde(tekst, jaar) or 'geschatte jaarlijkse parameter' not in tekst.lower()):
        blokkades.append('Geschatte jaarparameter niet bewezen')
    if naam == 'OCTA+ Boost Flex Gas' and not ('delen door 10' in tekst and
                                                 'cEUR/kWh' in tekst):
        blokkades.append('OCTA+ eenheidsconversie niet bewezen')
    bewijs_ok = not blokkades
    return {
        'tariefmaand': MAAND,
        'index': spec['index'],
        'historische_indexmaand': '2026-10' if historisch and bewijs_ok else None,
        'historische_waarde_eur_per_mwh': float(historisch.replace(',', '.')) if historisch and bewijs_ok else None,
        'geschatte_jaarparameter_eur_per_mwh': float(jaar.replace(',', '.')) if jaar and bewijs_ok else None,
        'index_in_prijsformule': 'cEUR/kWh' if naam.startswith('OCTA+') else 'EUR/MWh',
        'omrekening_van_eur_mwh_naar_formule_index': 'delen_door_10' if naam.startswith('OCTA+') else 'geen',
        'formule_factor': spec['factor'] if bewijs_ok else None,
        'formule_toeslag_ct_per_kwh_excl_btw': spec['toeslag'] if bewijs_ok else None,
        'bronbewijs_consistent': bewijs_ok,
        'indexwaarde_gevalideerd_voor_jaarprijs': False,
        'geschikt_voor_automatische_jaarprijs': False,
        'blokkades': blokkades + ['Volledige jaarprognose en contractvoorwaarden niet gevalideerd'],
        'opmerking': ('100 EUR/MWh in OCTA+-PDF is uitsluitend een rekenvoorbeeld, geen marktwaarde'
                      if naam.startswith('OCTA+') else 'Historische waarde is geen jaarprognose'),
    }


def main():
    data = json.loads(BRON.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Ongeldig gas_indexwaarden_bewijs.json')
    rapport = {
        'schema_version': 1,
        'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'bron': BRON.name,
        'referentiemaand': MAAND,
        'status': 'INDEX_GENORMALISEERD_GEEN_JAARPRIJSVALIDATIE',
        'voor_android_app': False,
        'contracten': {},
    }
    for naam, spec in SPEC.items():
        item = data['contracten'].get(naam)
        if not isinstance(item, dict):
            raise SystemExit('Ontbrekend contract in indexbewijs: ' + naam)
        rapport['contracten'][naam] = controleer(naam, item, spec)
        print(naam, 'BEWIJS OK' if rapport['contracten'][naam]['bronbewijs_consistent'] else 'GEBLOKKEERD')
    tmp = UITVOER.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(rapport, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(UITVOER)
    print('Rapport geschreven:', UITVOER)


if __name__ == '__main__':
    main()
