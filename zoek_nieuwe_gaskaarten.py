#!/usr/bin/env python3
"""Veilige, alleen-lezen ontdekking van nieuwe gas-PDF's in het SEF-archief.

Schrijft uitsluitend gas_gevonden_tariefkaarten.json; publiceert geen prijzen.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

URL = 'https://energieplatform-vlaanderen.be/tariefkaartarchief?energie=Gas&segment=Woning'
OUTPUT = Path('gas_gevonden_tariefkaarten.json')
TARGETS = {
    'ENGIE Flow Gas': ('ENGIE', 'Flow'),
    'Luminus BasicFlex Online Gas': ('Luminus', 'BasicFlex Online'),
    'OCTA+ Boost Flex Gas': ('OCTA+', 'Boost Flex'),
}
MONTHS = {'jan':1,'feb':2,'mrt':3,'apr':4,'mei':5,'jun':6,'jul':7,'aug':8,'sep':9,'okt':10,'nov':11,'dec':12}
MONTH_PATTERN = re.compile(r'Kaart\s+(jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)\s+(20\d{2})\s*\(PDF\)', re.I)

def norm(s):
    return re.sub(r'[^a-z0-9]+', '', s.casefold().replace('ï','i').replace('ë','e'))

def parse_archive(html):
    soup = BeautifulSoup(html, 'html.parser')
    # De website groepeert producten onder leverancier-h2's. Productregels
    # zijn tekst vlak voor de bijbehorende PDF-links. We gebruiken alleen
    # expliciete productlabels; geen fuzzy match met andere contracten.
    result = {name: [] for name in TARGETS}
    supplier = ''
    product = ''
    for node in soup.descendants:
        if getattr(node, 'name', None) == 'h2':
            supplier = node.get_text(' ', strip=True)
            product = ''
            continue
        if getattr(node, 'name', None) != 'a':
            continue
        label = node.get_text(' ', strip=True)
        match = MONTH_PATTERN.search(label)
        if not match:
            continue
        href = node.get('href', '')
        full_url = urljoin(URL, href)
        parsed = urlparse(full_url)
        if parsed.netloc != 'energieplatform-vlaanderen.be' or parsed.path != '/tariefkaartarchief':
            continue
        if not parse_qs(parsed.query).get('pdf'):
            continue
        # Zoek het dichtstbijzijnde voorafgaande productlabel, maar stop
        # zodra een ander PDF-anker of een h2 wordt bereikt.
        prev = node.previous_element
        product_text = ''
        for _ in range(45):
            if prev is None or getattr(prev, 'name', None) == 'h2':
                break
            if getattr(prev, 'name', None) == 'a' and prev is not node:
                break
            if isinstance(prev, str):
                candidate = prev.strip()
                if candidate and 'variabel' in candidate.casefold() and 'maanden' in candidate.casefold():
                    product_text = candidate
                    break
            prev = prev.previous_element
        if product_text:
            product = product_text
        month = f'{int(match.group(2)):04d}-{MONTHS[match.group(1).lower()]:02d}'
        for name, (company, contract) in TARGETS.items():
            if norm(company) not in norm(supplier):
                continue
            # Exact product prefix, gevolgd door het label 'variabel'.
            p = re.split(r'\s+variabel\b', product, maxsplit=1, flags=re.I)[0]
            p = re.sub(r'^' + re.escape(company) + r'\s*[–-]\s*', '', p, flags=re.I)
            if norm(p) == norm(contract):
                result[name].append({'tariefmaand_archief':month, 'pdf_url':full_url})
    return result

def main():
    response = requests.get(URL, timeout=40, headers={'User-Agent':'EerlijkeEnergie-GasBronzoeker/1.0'})
    response.raise_for_status()
    results = parse_archive(response.text)
    report = {'schema_version':1, 'status':'kandidaten_niet_gevalideerd',
              'archief_url':URL, 'gecontroleerd_op_utc':datetime.now(timezone.utc).isoformat(),
              'waarschuwing':'Archiefmaand en URL zijn slechts kandidaten. Controleer PDF-inhoud, indexeenheid en contract voordat formules of prijzen worden gepubliceerd.',
              'contracten':{}}
    for name, candidates in results.items():
        # Hoogste maand eerst, en verwijder identieke URL's.
        unique = {c['pdf_url']:c for c in candidates}
        ordered = sorted(unique.values(), key=lambda c:c['tariefmaand_archief'], reverse=True)
        report['contracten'][name] = {'gevonden':bool(ordered), 'kandidaten':ordered[:3]}
        print(f'{name}: {len(ordered)} archiefkaarten gevonden; nieuwste: {ordered[0]["tariefmaand_archief"] if ordered else "geen"}')
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Rapport geschreven: {OUTPUT}')

if __name__ == '__main__':
    main()
