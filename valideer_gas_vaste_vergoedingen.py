#!/usr/bin/env python3
"""Validate current annual fixed fees independently of contract eligibility."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse, parse_qs

SOURCE = Path('gas_vaste_vergoeding_kandidaten.json')
OUTPUT = Path('gas_vaste_vergoedingen_validatie.json')
METHODS = {'ENGIE Flow Gas': 'visuele_kolom', 'Luminus BasicFlex Online Gas': 'tabel', 'OCTA+ Boost Flex Gas': 'tabel'}
ANNUAL = re.compile(r'(?:€\s*/\s*jaar|euro\s*/\s*jaar|per\s+jaar|jaarlijkse)', re.I)
VAT = re.compile(r'incl(?:usief)?\.?\s*(?:6\s*%\s*)?btw', re.I)

def check(name, row, method, month):
    row = row if isinstance(row, dict) else {}
    problems = []
    if row.get('tariefmaand') != month:
        problems.append('Tariefmaand niet actueel')
    url = urlparse(str(row.get('pdf_url') or ''))
    digest = row.get('pdf_sha256')
    if not (isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest) and url.scheme == 'https' and url.hostname == 'energieplatform-vlaanderen.be' and parse_qs(url.query).get('pdf', [''])[0].lower() == digest and row.get('reden') == 'pdf_gecontroleerd_bedragen_nog_niet_gevalideerd'):
        problems.append('PDF-bronbewijs niet bevestigd')
    matches = []
    for c in row.get('kandidaten', []):
        if c.get('bron') != method or c.get('pagina') != 1:
            continue
        label = str(c.get('labelcel', ''))
        if 'vaste vergoeding' not in label.lower() or c.get('jaareenheid_bevestigd') is not True or not ANNUAL.search(label):
            continue
        try:
            value = Decimal(str(c.get('bedrag')))
            if value.is_finite() and 0 <= value <= 9999 and value == value.quantize(Decimal('0.01')):
                matches.append(value)
        except (InvalidOperation, TypeError, ValueError):
            continue
    if len(matches) != 1:
        problems.append('Geen uniek jaarlijks bedrag met bevestigd PDF-label')
    if not any(VAT.search(str(v.get('tekst', ''))) and v.get('pagina') == 1 for v in row.get('btw_bronregels', [])):
        problems.append('Inclusief btw niet bevestigd op prijspagina')
    ok = not problems
    return {'vast_bedrag_eur_incl_btw_per_jaar': format(matches[0], '.2f') if ok else None,
            'bedrag_en_pdf_bewijs_gecontroleerd': ok,
            'vaste_vergoeding_volledig_gevalideerd': ok,
            'pdf_sha256': digest, 'pdf_url': row.get('pdf_url'),
            'voorwaarden_bronregels': row.get('voorwaarden_bronregels', []),
            'voorwaarden_automatisch_gevalideerd': False,
            'geschikt_voor_automatische_jaarprijs': False,
            'blokkades': problems + ['Contractgeschiktheid afzonderlijk te valideren']}

def main():
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 2 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Onbekend formaat van kandidatenrapport')
    now = datetime.now(timezone.utc)
    month = now.strftime('%Y-%m')
    result = {name: check(name, data['contracten'].get(name), method, month) for name, method in METHODS.items()}
    output = {'schema_version': 1, 'gegenereerd_op_utc': now.isoformat(), 'bron': str(SOURCE), 'referentiemaand': month, 'status': 'VASTE_VERGOEDING_BEWIJSCONTROLE_GEEN_JAARPRIJZEN', 'voor_android_app': False, 'contracten': result}
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(OUTPUT)
    for name, row in result.items():
        print(f'{name}: bedrag/PDF={row["bedrag_en_pdf_bewijs_gecontroleerd"]}; blokkades={row["blokkades"]}')

if __name__ == '__main__':
    main()
