#!/usr/bin/env python3
"""Vind gas-tariefkaartkandidaten in de HTML van Energieplatform Vlaanderen.

Alleen-lezen: schrijft uitsluitend gas_gevonden_tariefkaarten.json.
De gevonden kaarten zijn NIET automatisch gevalideerde tarieven.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

URL = 'https://energieplatform-vlaanderen.be/tariefkaartarchief?energie=Gas&segment=Woning'
OUTPUT = Path('gas_gevonden_tariefkaarten.json')
TARGETS = {
    'ENGIE Flow Gas': ('ENGIE', 'Flow'),
    'Luminus BasicFlex Online Gas': ('Luminus', 'BasicFlex Online'),
    'OCTA+ Boost Flex Gas': ('OCTA+', 'Boost Flex'),
    'Ecofix Flexy Online': ('Ecofix', 'Flexy Online'),
    'TotalEnergies myEssential Variabel Gas': ('TotalEnergies', 'myEssential Variabel'),
}
MONTHS = {'jan': 1, 'feb': 2, 'mrt': 3, 'apr': 4, 'mei': 5, 'jun': 6,
          'jul': 7, 'aug': 8, 'sep': 9, 'okt': 10, 'nov': 11, 'dec': 12}
MONTH_PATTERN = re.compile(
    r'\bkaart\s+(jan|feb|mrt|apr|mei|jun|jul|aug|sep|okt|nov|dec)\s+(20\d{2})\b',
    re.IGNORECASE,
)

def norm(value):
    return re.sub(r'[^a-z0-9]+', '', value.casefold().replace('ï', 'i').replace('ë', 'e'))

def parse_archive(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {name: [] for name in TARGETS}
    for group in soup.select('[data-archief-groep]'):
        heading = group.find('h2')
        if heading is None:
            continue
        supplier = heading.get_text(' ', strip=True)
        for contract_element in group.select('details[data-zoek]'):
            if contract_element.get('data-type', '').casefold() != 'variabel':
                continue
            summary = contract_element.find('summary')
            title = summary.find('strong') if summary else None
            if title is None:
                continue
            product = title.get_text(' ', strip=True)
            for name, (company, contract) in TARGETS.items():
                if norm(company) not in norm(supplier):
                    continue
                # Contractnaam komt uit de summary, niet uit de PDF-link.
                expected = norm(contract)
                actual = norm(product)
                if actual not in (expected, norm(company + ' ' + contract), norm(contract + ' Gas'), norm(company + ' ' + contract + ' Gas')):
                    continue
                allowed_months = set(contract_element.get('data-maanden', '').split())
                for link in contract_element.select('li a[href]'):
                    match = MONTH_PATTERN.search(link.get_text(' ', strip=True))
                    if not match:
                        continue
                    month = f'{match.group(2)}-{MONTHS[match.group(1).lower()]:02d}'
                    if allowed_months and month not in allowed_months:
                        continue
                    full_url = urljoin(URL, link['href'])
                    parsed = urlparse(full_url)
                    if parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be':
                        continue
                    if parsed.path.rstrip('/') != '/tariefkaartarchief':
                        continue
                    pdf_ids = parse_qs(parsed.query).get('pdf', [])
                    if len(pdf_ids) != 1 or not re.fullmatch(r'[0-9a-fA-F]{64}', pdf_ids[0]):
                        continue
                    result[name].append({'tariefmaand_archief': month, 'pdf_url': full_url})
    return result

def main():
    response = requests.get(URL, timeout=40, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; EerlijkeEnergie-GasBronzoeker/2.0)'})
    response.raise_for_status()
    result = parse_archive(response.text)
    report = {
        'schema_version': 1,
        'status': 'kandidaten_niet_gevalideerd',
        'archief_url': URL,
        'gecontroleerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'waarschuwing': 'Archiefmaand en PDF-link zijn kandidaten, geen bevestiging van prijsformule, indexwaarde, contractgeldigheid of jaarprijs.',
        'contracten': {},
    }
    for name, candidates in result.items():
        unique = {item['pdf_url']: item for item in candidates}
        ordered = sorted(unique.values(), key=lambda item: item['tariefmaand_archief'], reverse=True)
        report['contracten'][name] = {'gevonden': bool(ordered), 'aantal': len(ordered), 'kandidaten': ordered[:3]}
        newest = ordered[0]['tariefmaand_archief'] if ordered else 'geen'
        print(f'{name}: {len(ordered)} archiefkaarten gevonden; nieuwste: {newest}')
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Rapport geschreven: {OUTPUT}')

if __name__ == '__main__':
    main()
