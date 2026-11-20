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
METHODS = {
    'ENGIE Flow Gas': 'visuele_kolom',
    'Luminus BasicFlex Online Gas': 'tabel',
    'OCTA+ Boost Flex Gas': 'tabel',
    'Ecofix Flexy Online': 'visuele_kolom',
    'TotalEnergies myEssential Variabel Gas': 'tabel',
}
ANNUAL = re.compile(r'(?:€\s*/\s*jaar|euro\s*/\s*jaar|per\s+jaar|jaarlijkse)', re.I)
VAT = re.compile(r'(?:incl(?:usief)?\.?\s*(?:6\s*%\s*)?btw|btw\s+6\s*%\s*inbegrepen)', re.I)

def eligibility(row, source_ok):
    keys = ('domiciliering_verplicht', 'aandelen_verplicht', 'groepsaankoop_verplicht',
            'digitale_meter_verplicht', 'zonnepanelen_verplicht', 'analoge_meter_toegelaten',
            'variabel_contract', 'particuliere_klant', 'netgebied')
    values = dict.fromkeys(keys, 'onbekend')
    evidence = {}
    rules = row.get('geschiktheid_bronregels', []) if source_ok else []
    patterns = {
        'variabel_contract': ('ja', r'\(type\s*:\s*variabel\)|tarief\s*:\s*variabel|variabel aardgastarief'),
        'particuliere_klant': ('ja', r'voor particulieren|geldig voor residentiële klanten|verbruikers\s*:\s*residentieel'),
        'netgebied': ('ja', r'^fluvius antwerpen\s+\d'),
        'domiciliering_verplicht': ('nee', r'u kiest ook uw betaalwijze\s*\(domiciliëring,\s*(?:[^|]{0,180}?contract op de startdatum\s+)?overschrijving of enige andere door luminus aangeboden betaalwijze\)'),
    }
    for key, (value, pattern) in patterns.items():
        for rule in rules:
            # Context is needed for clauses split across lines. Other checks use
            # the actual line, except the residential heading in its local context.
            field = 'context' if key in ('domiciliering_verplicht', 'particuliere_klant') else 'tekst'
            content = re.sub(r'\s*(?:\|\s*)+', ' ', str(rule.get(field, '')))
            if re.search(pattern, content, re.I):
                values[key] = value
                evidence[key] = rule
                break
    # Positive proof of the basic profile does not establish absence of restrictions.
    expected = {k: 'nee' for k in keys[:5]}
    expected.update({k: 'ja' for k in keys[5:]})
    missing = [k for k in keys if values[k] != expected[k]]
    return values, evidence, missing

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
        label_ok = 'vaste vergoeding' in label.lower()
        if name == 'Ecofix Flexy Online':
            label_ok = label_ok or bool(re.fullmatch(
                r'vaste\s+vergoed\s+prijs\s+per\s+kwh\s*\(€\s*cent/kwh\)\s*\(€\s*/\s*jaar\)',
                label.strip(), re.I
            ))
        if not label_ok or c.get('jaareenheid_bevestigd') is not True or not ANNUAL.search(label):
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
    values, evidence, missing = eligibility(row, ok)
    eligibility_ok = ok and not missing
    return {'vast_bedrag_eur_incl_btw_per_jaar': format(matches[0], '.2f') if ok else None,
            'bedrag_en_pdf_bewijs_gecontroleerd': ok,
            'vaste_vergoeding_volledig_gevalideerd': ok,
            'pdf_sha256': digest, 'pdf_url': row.get('pdf_url'),
            'voorwaarden_bronregels': row.get('voorwaarden_bronregels', []),
            'geschiktheid': values, 'geschiktheid_bewijs': evidence,
            'geschiktheid_openstaande_criteria': missing,
            'voorwaarden_automatisch_gevalideerd': eligibility_ok,
            'geschikt_voor_automatische_jaarprijs': False,
            'blokkades': problems + (['Contractgeschiktheid: ' + k for k in missing] if not eligibility_ok else [])}

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
