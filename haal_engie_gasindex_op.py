#!/usr/bin/env python3
"""Voeg ENGIE ZTP DAM toe aan bestaand leveranciersrapport; behoud OCTA+.

Fail-closed: enkel ondubbelzinnige HTML-tabellen met expliciete kolomkop.
Geen jaarprijs of prognosevalidatie.
"""
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import requests

URL = 'https://www.engie.be/nl/energie/elektriciteit-gas/prijzen-voorwaarden/indexatieparameters/indexatieparameters-gas'
PATH = Path('gas_indexen_leveranciers.json')
MONTHS = {'januari': 1, 'februari': 2, 'maart': 3, 'april': 4, 'mei': 5,
          'juni': 6, 'juli': 7, 'augustus': 8, 'september': 9,
          'oktober': 10, 'november': 11, 'december': 12}


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table' and self.table is None:
            self.table = []
        elif self.table is not None and tag == 'tr':
            self.row = []
        elif self.row is not None and tag in ('th', 'td'):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('th', 'td') and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r'\s+', ' ', ' '.join(self.cell)).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None and self.table is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def parse_month(s):
    m = re.search(r'\b(' + '|'.join(MONTHS) + r')\s+(20\d{2})\b', s.lower())
    return f'{int(m.group(2)):04d}-{MONTHS[m.group(1)]:02d}' if m else None


def parse_number(s):
    s = s.strip().replace('\xa0', '')
    if not re.fullmatch(r'\d{1,3}(?:[.,]\d{1,4})?', s):
        return None
    n = float(s.replace(',', '.'))
    return n if 1 <= n <= 1000 else None


def parse_engie(html, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    p = Tables()
    p.feed(html)
    # ENGIE publiceert meerdere tabellen (o.a. responsive weergaven).
    # Oktober 2026 blijft een historisch controleanker; nieuwe maanden zijn toegestaan.
    valid_tables = []
    for table in p.tables:
        for hi, header in enumerate(table):
            norm = [re.sub(r'[^a-z0-9]+', '', c.lower()) for c in header]
            matches = [i for i, c in enumerate(norm) if c in ('ztpdam', 'waardeztpdam')]
            if len(matches) != 1:
                continue
            col = matches[0]
            grouped = {}
            conflict = False
            for row in table[hi + 1:]:
                month = parse_month(row[0]) if row else None
                if month is None or col >= len(row):
                    continue
                value = parse_number(row[col])
                if value is None or month >= today.strftime('%Y-%m'):
                    continue
                if month in grouped and abs(grouped[month] - value) > 0.00001:
                    conflict = True
                    break
                grouped[month] = value
            if (not conflict and '2026-10' in grouped
                    and abs(grouped['2026-10'] - 85.777) <= 0.002):
                valid_tables.append(grouped)
            break
    if not valid_tables:
        raise ValueError('Geen ENGIE-tabel met juiste ZTP DAM-kolom en gecontroleerde oktoberreferentie')
    # Alleen maanden accepteren waar alle bruikbare tabellen het over eens zijn.
    grouped = {}
    for month in set().union(*(t.keys() for t in valid_tables)):
        values = [t[month] for t in valid_tables if month in t]
        if max(values) - min(values) <= 0.00001:
            grouped[month] = values[0]
    if not grouped:
        raise ValueError('Geen onderling consistente ENGIE-maandwaarden')
    # November 2026 test reference: historical October 2026 must match the tariff card.
    if '2026-10' in grouped and abs(grouped['2026-10'] - 85.777) > 0.002:
        raise ValueError('ENGIE oktober 2026 wijkt af van gecontroleerde tariefkaart')
    last = max(grouped)
    # Een oude publicatie mag nooit stilzwijgend als actuele index gelden.
    last_complete = (today.replace(day=1) - dt.timedelta(days=1)).strftime('%Y-%m')
    if last > last_complete:
        raise ValueError('ENGIE indexmaand nog niet afgesloten')
    return {'status': 'HISTORISCHE_INDEX_GEVONDEN', 'bron_url': URL,
            'index': 'ZTPDAM (Heren)', 'index_definitie': 'ZTP DAM',
            'laatste_volledige_maand': last, 'waarde_eur_per_mwh': grouped[last],
            'waarde_ct_per_kwh': round(grouped[last] / 10, 6),
            'aantal_historische_maanden': len(grouped),
            'jaarprognose_gevalideerd': False,
            'geschikt_voor_automatische_jaarprijs': False}


def main():
    if not PATH.is_file():
        raise SystemExit('Eerst haal_gasindexen_op.py uitvoeren: rapport ontbreekt')
    report = json.loads(PATH.read_text(encoding='utf-8'))
    if 'OCTA+ Boost Flex Gas' not in report.get('contracten', {}):
        raise SystemExit('OCTA+-record ontbreekt; bestaand rapport niet overschrijven')
    try:
        r = requests.get(URL, timeout=30, headers={'User-Agent': 'EerlijkeEnergie/1.0 (indexcontrole)'})
        r.raise_for_status()
        if 'html' not in r.headers.get('Content-Type', '').lower():
            raise ValueError('ENGIE-bron is geen HTML')
        entry = parse_engie(r.text)
    except (requests.RequestException, ValueError) as exc:
        entry = {'status': 'BRONFORMAAT_OF_WAARDE_NOG_NIET_GEVALIDEERD',
                 'bron_url': URL, 'index': 'ZTPDAM (Heren)',
                 'reden': f'{type(exc).__name__}: {str(exc)[:240]}',
                 'jaarprognose_gevalideerd': False,
                 'geschikt_voor_automatische_jaarprijs': False}
    report['contracten']['ENGIE Flow Gas'] = entry
    report['voor_android_app'] = False
    PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('ENGIE:', entry['status'])
    print('OCTA+ ongewijzigd:', report['contracten']['OCTA+ Boost Flex Gas']['status'])


if __name__ == '__main__':
    main()
