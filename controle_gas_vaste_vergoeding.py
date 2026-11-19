#!/usr/bin/env python3
"""Onderzoek vaste gasvergoeding in gehashte tariefkaart-PDF's.

Rapport is bewijsmateriaal, geen automatische prijsgoedkeuring.
Vervangt controle_gas_vaste_vergoeding.py; workflow blijft ongewijzigd.
"""
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pdfplumber
import requests
from controle_gas_tariefkaarten import lees_pdf

SOURCE = Path('gas_archiefformules_vergelijking.json')
OUTPUT = Path('gas_vaste_vergoeding_kandidaten.json')
LABEL = re.compile(r'vaste\s+(?:vergoeding|bijdrage|kosten)', re.I)
ANNUAL = re.compile(r'(?:€\s*/\s*jaar|euro\s*/\s*jaar|per\s+jaar|jaarlijkse)', re.I)
MONEY = re.compile(r'(?<![\d.,])(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)(?![\d.,])')
VAT = re.compile(r'(?:incl(?:usief)?\.?\s*(?:6\s*%\s*)?btw|prijzen\s+.*incl\.?\s*6\s*%\s*btw)', re.I)
CONDITIONS = re.compile(r'(?:vroegtijdig|beëindig|beeindig|6\s+maanden|half\s+jaar|aantal\s+dagen|pro\s*rata|leveringsdagen)', re.I)


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def extract_evidence(pdf_bytes):
    """Preserve page and row references; never infer fees from arbitrary nearby amounts."""
    candidates = []
    vat_evidence = []
    condition_evidence = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page_no, page in enumerate(document.pages, 1):
            lines = (page.extract_text(layout=False) or '').splitlines()
            for i, line in enumerate(lines):
                line = clean(line)
                if VAT.search(line):
                    vat_evidence.append({'pagina': page_no, 'tekst': line[:450]})
                if CONDITIONS.search(line) and (LABEL.search(line) or 'vergoeding' in line.lower()):
                    condition_evidence.append({'pagina': page_no, 'tekst': line[:450]})
                if LABEL.search(line):
                    context = ' | '.join(clean(x) for x in lines[max(0, i-1):min(len(lines), i+3)])
                    candidates.append({'bron': 'tekst', 'pagina': page_no, 'regel': i+1,
                                       'tekst': context[:650], 'bedrag': None,
                                       'status': 'context_niet_automatisch_toegewezen'})
            for table_no, table in enumerate(page.extract_tables() or [], 1):
                for row_no, row in enumerate(table or [], 1):
                    cells = [clean(c) for c in (row or [])]
                    for col, cell in enumerate(cells):
                        if not LABEL.search(cell):
                            continue
                        # The label's own cell and the immediately adjacent cell are evidence,
                        # but only a sole numeric cell qualifies as a plausible fee candidate.
                        adjacent = cells[col+1] if col+1 < len(cells) else ''
                        own_numbers = MONEY.findall(cell)
                        adjacent_numbers = MONEY.findall(adjacent)
                        amount = None
                        confidence = 'handmatige_controle_nodig'
                        if not own_numbers and re.fullmatch(r'\s*€?\s*\d{1,4}(?:[.,]\d{1,2})?\s*€?\s*', adjacent):
                            amount = adjacent.replace('€', '').strip().replace(',', '.')
                            confidence = 'tabelcel_kandidaat_niet_gevalideerd'
                        candidates.append({'bron': 'tabel', 'pagina': page_no,
                                           'tabel': table_no, 'rij': row_no,
                                           'labelcel': cell[:250], 'naastliggende_cel': adjacent[:250],
                                           'rijtekst': ' | '.join(cells)[:650],
                                           'bedrag': amount, 'status': confidence})
    return candidates[:70], vat_evidence[:15], condition_evidence[:20]


def inspect(name, info, session):
    result = {'status': 'handmatige_controle_nodig', 'vaste_vergoeding_gevalideerd': False,
              'tariefmaand': info.get('tariefmaand_archief'), 'pdf_url': info.get('pdf_url'),
              'kandidaten': [], 'btw_bronregels': [], 'voorwaarden_bronregels': []}
    if info.get('status') != 'formule_gelijk_aan_referentie' or info.get('formule_gelijk') is not True:
        result['reden'] = 'formulevergelijking_niet_geslaagd'
        return result
    url = info.get('pdf_url')
    if not isinstance(url, str):
        result['reden'] = 'ontbrekende_pdf_url'
        return result
    parsed = urlparse(url)
    sha = parse_qs(parsed.query).get('pdf', [''])[0].lower()
    if (parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be'
            or not re.fullmatch(r'[0-9a-f]{64}', sha)):
        result['reden'] = 'onbetrouwbare_pdf_url'
        return result
    try:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        raw = response.content
        
        if not raw.startswith(b'%PDF-') or len(raw) > 15_000_000:
            raise ValueError('geen_geldige_pdf')
        digest = hashlib.sha256(raw).hexdigest()

