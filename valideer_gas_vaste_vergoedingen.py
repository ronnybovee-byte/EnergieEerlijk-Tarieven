#!/usr/bin/env python3
"""Fail-closed validation of November 2026 gas fixed fees from PDF evidence.

Only fixed-fee evidence is assessed; NEVER approves complete gas annual prices.
New months and changed PDFs require new independently reviewed baselines.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation

SOURCE = Path('gas_vaste_vergoeding_kandidaten.json')
OUTPUT = Path('gas_vaste_vergoedingen_validatie.json')
BASELINES = {
    'ENGIE Flow Gas': {'amount': '50.00', 'source': 'visuele_kolom', 'sha256': 'dc12088e63cec5de4e893c6ed2003903804ad794b2b31d08257f3e30ce222da1'},
    'Luminus BasicFlex Online Gas': {'amount': '20.00', 'source': 'tabel', 'sha256': 'd1105da725c750ad6570110124ad0eab588d12f27706107efadf84453d467b65'},
    'OCTA+ Boost Flex Gas': {'amount': '65.00', 'source': 'tabel', 'sha256': '432590afb3a59d20b4f0050ce67166b7b576aed062da530bcb838a4e49b1e9b0'},
}

def check(name, row, baseline):
    problems = []
    if not isinstance(row, dict):
        return {'vaste_vergoeding_gevalideerd': False, 'blokkades': ['Contract ontbreekt']}
    if row.get('tariefmaand') != '2026-11':
        problems.append('Nieuwe of afwijkende tariefmaand: nieuwe referentiecontrole nodig')
    if row.get('pdf_sha256') != baseline['sha256']:
        problems.append('PDF-hash wijkt af van gecontroleerde novemberreferentie')
    if row.get('reden') != 'pdf_gecontroleerd_bedragen_nog_niet_gevalideerd':
        problems.append('PDF-controle niet geslaagd')
    matches = []
    for candidate in row.get('kandidaten', []):
        if candidate.get('bron') != baseline['source'] or candidate.get('pagina') != 1:
            continue
        if 'vaste vergoeding' not in str(candidate.get('labelcel', '')).lower():
            continue
        try:
            amount = Decimal(str(candidate.get('bedrag')))
        except (InvalidOperation, TypeError):
            continue
        matches.append(amount)
    expected = Decimal(baseline['amount'])
    if matches != [expected]:
        problems.append('Geen uniek, correct bedrag in verwachte PDF-tabel/kolom')
    vat = ' '.join(str(x.get('tekst', '')) for x in row.get('btw_bronregels', []))
    if 'btw' not in vat.lower() or not ('incl' in vat.lower()):
        problems.append('Geen bewijs dat tariefkaart inclusief btw vermeldt')
    if name != 'OCTA+ Boost Flex Gas' and '6%' not in vat.replace(' ', ''):
        problems.append('6%-btw-vermelding niet gevonden')
    if name == 'OCTA+ Boost Flex Gas' and '6%' not in vat.replace(' ', ''):
        problems.append('Exact btw-percentage OCTA+ niet bevestigd in bronregels')
    conditions = ' '.join(str(x.get('tekst', '')) for x in row.get('voorwaarden_bronregels', []))
    if not conditions:
        problems.append('Contractvoorwaarden niet gevonden')
    # The fee can be evidence-confirmed independently of conditions, but do not
    # imply those conditions are machine-validated or that annual prices are ready.
    fee_confirmed = not any('btw-percentage' not in p and 'Contractvoorwaarden' not in p for p in problems)
    return {
        'vast_bedrag_eur_incl_btw_per_jaar': baseline['amount'] if fee_confirmed else None,
        'bedrag_en_pdf_bewijs_gecontroleerd': fee_confirmed,
        'vaste_vergoeding_volledig_gevalideerd': len(problems) == 0,
        'voorwaarden_automatisch_gevalideerd': False,
        'geschikt_voor_automatische_jaarprijs': False,
        'blokkades': problems + ['Voorwaarden niet automatisch inhoudelijk gevalideerd', 'Indexwaarden en volledige jaarprijs niet gevalideerd'],
    }

def main():
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 2 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Onbekend formaat van kandidatenrapport')
    result = {name: check(name, data['contracten'].get(name), base) for name, base in BASELINES.items()}
    output = {'schema_version': 1, 'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
              'bron': str(SOURCE), 'referentiemaand': '2026-11',
              'status': 'VASTE_VERGOEDING_BEWIJSCONTROLE_GEEN_JAARPRIJZEN',
              'voor_android_app': False, 'contracten': result}
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    for name, r in result.items():
        print(f'{name}: bedrag/PDF={r["bedrag_en_pdf_bewijs_gecontroleerd"]}; volledige jaarprijs=GEBLOKKEERD')
    print('Rapport:', OUTPUT)

if __name__ == '__main__':
    main()
