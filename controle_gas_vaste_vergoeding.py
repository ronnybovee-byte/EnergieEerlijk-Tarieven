#!/usr/bin/env python3
"""Onderzoek vaste gasvergoeding in gehashte tariefkaart-PDF's.

Rapport is bewijsmateriaal, geen automatische prijsgoedkeuring.
Jaareenheid moet expliciet uit de PDF blijken.
Vervangt controle_gas_vaste_vergoeding.py; workflow blijft ongewijzigd.
"""
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fitz
import pdfplumber
import requests
from controle_gas_tariefkaarten import lees_pdf

SOURCE = Path('gas_archiefformules_vergelijking.json')
OUTPUT = Path('gas_vaste_vergoeding_kandidaten.json')
LABEL = re.compile(r'vaste\s+(?:vergoeding|bijdrage|kosten)', re.I)
ANNUAL = re.compile(r'(?:€\s*/\s*jaar|euro\s*/\s*jaar|per\s+jaar|jaarlijkse)', re.I)
MONEY = re.compile(r'(?<![\d.,])(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)(?![\d.,])')
VAT = re.compile(r'(?:incl(?:usief)?\.?\s*(?:6\s*%\s*)?btw|prijzen\s+.*incl\.?\s*6\s*%\s*btw|btw\s+6\s*%\s*inbegrepen)', re.I)
CONDITIONS = re.compile(r'(?:vroegtijdig|beëindig|beeindig|6\s+maanden|half\s+jaar|aantal\s+dagen|pro\s*rata|leveringsdagen)', re.I)


# Alleen bronpassages verzamelen: geen geschiktheid afleiden uit trefwoorden.
GESCHIKTHEID = {
    'domiciliering_verplicht': r'domicili[ëe]r|automatische\s+incasso|sepa',
    'aandelen_verplicht': r'aandeel|aandelen|aandeelhouder|co[oö]perant',
    'groepsaankoop_verplicht': r'groepsaankoop|groepscontract',
    'digitale_meter_verplicht': r'digitale\s+(?:gas)?meter|slimme\s+meter',
    'zonnepanelen_verplicht': r'zonnepanelen|fotovolta|prosument',
    'analoge_meter_toegelaten': r'analog[e]?\s+meter|klassieke\s+meter|traditionele\s+meter|mechanische\s+meter',
    'variabel_contract': r'variabel|indexatie|ge[iï]ndexeerd',
    'particuliere_klant': r'particulier|residenti[ëe]l|huishoudelijk|priv[eé]',
    'netgebied': r'vlaanderen|vlaams|fluvius|antwerpen',
}


def geschiktheidsbewijs(tekst, pagina):
    regels = [clean(x) for x in tekst.splitlines() if clean(x)]
    bewijs = []
    for i, regel in enumerate(regels):
        criteria = [k for k, patroon in GESCHIKTHEID.items()
                    if re.search(patroon, regel, re.I)]
        if criteria:
            bewijs.append({'pagina': pagina, 'regel': i+1,
                           'criteria': criteria,
                           'tekst': regel,
                           'context': ' | '.join(regels[max(0, i-1):i+3])})
    return bewijs


def clean(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def extract_evidence(pdf_bytes, name):
    """Preserve page and row references; never infer fees from arbitrary nearby amounts."""
    candidates = []
    vat_evidence = []
    condition_evidence = []
    eligibility_evidence = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for page_no, page in enumerate(document.pages, 1):
            page_text = page.extract_text(layout=False) or ''
            eligibility_evidence.extend(geschiktheidsbewijs(page_text, page_no))
            lines = page_text.splitlines()
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
            # ENGIE Flow: de vergoeding staat onder de kop in een afzonderlijk
            # visueel vak, niet in een naastliggende PDF-tabelcel.
            # Beperk tot de energieprijssectie boven "Netwerkkosten".
            if name == 'ENGIE Flow Gas' and page_no == 1:
                words = page.extract_words()
                labels = [w for w in words if w['text'].lower() == 'vaste' and 300 < w['top'] < 490]
                for label in labels:
                    same_line = [w for w in words if abs(w['top'] - label['top']) < 9 and label['x0'] <= w['x0'] < 310]
                    if not any('vergoeding' in w['text'].lower() for w in same_line):
                        continue
                    # Use actual printed text in the heading area, not an invented unit.
                    heading = clean(page.crop((label['x0'] - 2, max(0, label['top'] - 3), 310, min(page.height, label['top'] + 12))).extract_text() or '')
                    if not LABEL.search(heading) or not ANNUAL.search(heading):
                        continue
                    amounts = [w for w in words
                               if label['top'] + 12 < w['top'] < min(label['top'] + 90, 490)
                               and 70 < w['x0'] < 310
                               and re.fullmatch(r'\d{1,4},\d{2}', w['text'])]
                    if len(amounts) == 1:
                        amount = amounts[0]
                        candidates.append({'bron': 'visuele_kolom', 'pagina': page_no,
                                           'labelcel': heading,
                                           'jaareenheid_bevestigd': True,
                                           'bedrag': amount['text'].replace(',', '.'),
                                           'positie': {'x': round(amount['x0'], 1),
                                                       'y': round(amount['top'], 1)},
                                           'status': 'visuele_kandidaat_niet_gevalideerd'})
                if name == 'Ecofix Flexy Online' and page_no == 1:
                heading, _ = lees_pdf(pdf_bytes)
                heading = clean(heading)
                label = re.search(
                    r'vaste\s+vergoeding\s*\(?\s*€\s*/\s*jaar\s*\)?',
                    heading, re.I
                )
                if label:
                    amounts = [
                        w for w in page.extract_words()
                        if 0.18 < w['x0'] / page.width < 0.37
                        and 0.51 < w['top'] / page.height < 0.56
                        and re.fullmatch(r'\d{1,4}[,.]\d{2}', w['text'])
                    ]
                    if len(amounts) == 1:
                        candidates.append({
                            'bron': 'visuele_kolom',
                            'pagina': page_no,
                            'labelcel': label.group(0),
                            'jaareenheid_bevestigd': True,
                            'bedrag': amounts[0]['text'].replace(',', '.'),
                            'status': 'visuele_kandidaat_niet_gevalideerd'
                        })           
            for table_no, table in enumerate(page.extract_tables() or [], 1):
                for row_no, row in enumerate(table or [], 1):
                    cells = [clean(c) for c in (row or [])]
                    for col, cell in enumerate(cells):
                        if not LABEL.search(cell):
                            continue
                        # The label's own cell and the immediately adjacent cell are evidence,
                        # but only a sole numeric cell qualifies as a plausible fee candidate.
                        adjacent = cells[col+1] if col+1 < len(cells) else ''
                        if name == 'TotalEnergies myEssential Variabel Gas':
                            if ANNUAL.search(cell) and len(cells) == 1:
                                if row_no < len(table):
                                    below = clean(table[row_no][col])
                                    if re.fullmatch(r'\d{1,4}[,.]\d{2}', below):
                                        candidates.append({
                                            'bron': 'tabel',
                                            'pagina': page_no,
                                            'tabel': table_no,
                                            'rij': row_no,
                                            'labelcel': cell,
                                            'onderliggende_cel': below,
                                            'bedrag': below.replace(',', '.'),
                                            'jaareenheid_bevestigd': True,
                                            'status': 'tabelcel_kandidaat_niet_gevalideerd'
                                        })
                        own_numbers = MONEY.findall(cell)
                        adjacent_numbers = MONEY.findall(adjacent)
                        amount = None
                        confidence = 'handmatige_controle_nodig'
                        if ANNUAL.search(cell) and not own_numbers and re.fullmatch(r'\s*€?\s*\d{1,4}(?:[.,]\d{1,2})?\s*€?\s*', adjacent):
                            amount = adjacent.replace('€', '').strip().replace(',', '.')
                            confidence = 'tabelcel_kandidaat_niet_gevalideerd'
                        candidates.append({'bron': 'tabel', 'pagina': page_no,
                                           'tabel': table_no, 'rij': row_no,
                                           'labelcel': cell[:250], 'naastliggende_cel': adjacent[:250],
                                           'rijtekst': ' | '.join(cells)[:650],
                                           'bedrag': amount, 'jaareenheid_bevestigd': bool(ANNUAL.search(cell)), 'status': confidence})
    return candidates[:70], vat_evidence[:15], condition_evidence[:20], eligibility_evidence


def inspect(name, info, session):
    result = {'status': 'handmatige_controle_nodig', 'vaste_vergoeding_gevalideerd': False,
              'tariefmaand': info.get('tariefmaand_archief'), 'pdf_url': info.get('pdf_url'),
              'kandidaten': [], 'btw_bronregels': [], 'voorwaarden_bronregels': [],
              'geschiktheid_bronregels': [],
              'geschiktheid': {k: 'onbekend' for k in GESCHIKTHEID}}
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
        if digest != sha or digest != info.get('sha256'):
            raise ValueError('pdf_hash_verschilt')
        # Keep compatibility with existing OCR path, while tables are extracted
        # directly from the original PDF to preserve cell boundaries.
            ocr_text, ocr_pages = lees_pdf(raw)
        candidates, vat, conditions, eligibility = extract_evidence(raw, name)
        if name == 'Ecofix Flexy Online':
            with fitz.open(stream=raw, filetype='pdf') as document:
                for page_no in range(len(document)):
                    with fitz.open() as single:
                        single.insert_pdf(
                            document,
                            from_page=page_no,
                            to_page=page_no
                        )
                        page_text, _ = lees_pdf(single.tobytes())

                    eligibility.extend(
                        geschiktheidsbewijs(page_text, page_no + 1)
                    )

                    for line in page_text.splitlines():
                        line = clean(line)
                        if VAT.search(line):
                            vat.append({
                                'pagina': page_no + 1,
                                'tekst': line[:450],
                                'bron': 'ocr'
                            })
                        if CONDITIONS.search(line) and (
                            LABEL.search(line)
                            or 'vergoeding' in line.lower()
                        ):
                            conditions.append({
                                'pagina': page_no + 1,
                                'tekst': line[:450],
                                'bron': 'ocr'
                            })
        result.update({'pdf_sha256': digest, 'ocr_paginas': ocr_pages,
                       'kandidaten': candidates, 'btw_bronregels': vat,
                       'voorwaarden_bronregels': conditions,
                       'geschiktheid_bronregels': eligibility,
                       'reden': 'pdf_gecontroleerd_bedragen_nog_niet_gevalideerd'})
    except (requests.RequestException, ValueError, RuntimeError, Exception) as exc:
        result['reden'] = 'pdf_controle_mislukt: ' + str(exc)[:180]
    return result


def main():
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Ongeldig bronrapport')
    report = {'schema_version': 2, 'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'PDF_TABEL_EN_TEKST_KANDIDATEN_GEEN_AUTOMATISCHE_GOEDKEURING',
              'voor_android_app': False,
              'waarschuwing': 'Tabelkandidaten, btw en voorwaarden blijven handmatig te valideren.',
              'contracten': {}}
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'EerlijkeEnergie-GasVasteVergoedingControle/2.0'})
        for name, info in data['contracten'].items():
            report['contracten'][name] = inspect(name, info, session)
            print(name, report['contracten'][name]['reden'])
    temp = OUTPUT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(OUTPUT)
    print('Rapport:', OUTPUT)


if __name__ == '__main__':
    main()
