#!/usr/bin/env python3
"""Conservatieve Luminus TTFDAHM extractie; wijzigt bestaande JSON niet."""
import argparse
import datetime as dt
import io
import json
import re
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber

MONTHS = ['Januari','Februari','Maart','April','Mei','Juni','Juli','Augustus','September','Oktober','November','December']


INDEX_PAGE = 'https://www.luminus.be/nl/prive/energie/indexatieparameters/'

class DownloadLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []
    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((self.href, ' '.join(self.label)))
            self.href = None

def discover_pdf_url(session):
    response = session.get(INDEX_PAGE, timeout=30, headers={'User-Agent':'Mozilla/5.0'})
    response.raise_for_status()
    parser = DownloadLinks()
    parser.feed(response.text)
    candidates = []
    for href, label in parser.links:
        url = urljoin(INDEX_PAGE, href)
        if 'download indexatieparameters' in label.casefold() and urlparse(url).hostname == 'www.luminus.be':
            candidates.append(url)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError(f'Geen eenduidige officiële downloadlink: {len(candidates)} kandidaten')
    return candidates[0]

def parse_pdf(data):
    """Read the TTFDAHM column by printed year, not a fixed October position."""
    with pdfplumber.open(io.BytesIO(data)) as doc:
        page = doc.pages[0]
        words = page.extract_words()
        text = page.extract_text() or ''
    if 'TTFDAHM' not in text.replace(' ', ''):
        raise ValueError('TTFDAHM niet aanwezig')
    matches = re.findall(r'\b(' + '|'.join(MONTHS) + r')\s+(20\d{2})\b', text, re.I)
    matches = list(dict.fromkeys((m.capitalize(), int(y)) for m, y in matches))
    if len(matches) != 1:
        raise ValueError(f'Tariefmaand niet eenduidig: {matches}')
    tariff_month_name, tariff_year = matches[0]
    tariff_month = MONTHS.index(tariff_month_name) + 1
    tariff_date = dt.date(tariff_year, tariff_month, 1)
    prev = tariff_date - dt.timedelta(days=1)
    historic_month = f'{prev.year:04d}-{prev.month:02d}'
    region = [w for w in words if 225 <= w['x0'] <= 385 and w['top'] > 330]
    def numeric(w):
        return bool(re.fullmatch(r'\d{1,3},\d{3}', w['text']))
    def number(w):
        return float(w['text'].replace(',', '.'))
    # Printed years are the column headers; only the most recent year's column is eligible.
    headers = [w for w in region if w['text'] == str(prev.year) and 340 <= w['top'] <= 365]
    if len(headers) != 1:
        raise ValueError(f'Jaarheader {prev.year} ontbreekt of is dubbel')
    x = headers[0]['x0']
    label = MONTHS[prev.month - 1]
    labels = [w for w in region if w['text'].casefold() == label.casefold() and 360 < w['top'] < 510]
    if len(labels) != 1:
        raise ValueError(f'Indexrij {label} niet eenduidig')
    row = [w for w in region if abs(w['top'] - labels[0]['top']) < 2 and numeric(w)]
    values = [w for w in row if abs(w['x0'] - x) < 7]
    if len(values) != 1:
        raise ValueError(f'Geen eenduidige TTFDAHM-waarde voor {historic_month}')
    hist = number(values[0])
    fw = [w for w in region if w['text'] == 'Forward*' and 480 < w['top'] < 525]
    if len(fw) != 1:
        raise ValueError('Forwardrij niet eenduidig')
    fvals = [w for w in region if abs(w['top'] - fw[0]['top']) < 2 and numeric(w) and w['x0'] >= x - 7]
    if len(fvals) != 1:
        raise ValueError('Forwardwaarde niet eenduidig')
    forward = number(fvals[0])
    if not (1 < hist < 1000 and 1 < forward < 1000):
        raise ValueError('Index buiten controlebereik')
    # Guard against a future-dated or obsolete PDF. A missing new PDF is NOT a success.
    current = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m')
    tariff = tariff_date.strftime('%Y-%m')
    if tariff > current:
        raise ValueError('Tariefmaand ligt in de toekomst')
    return hist, forward, tariff, historic_month

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pdf',help='Lokale Luminus PDF (voor controle/test)')
    ap.add_argument('--url',help='Expliciete directe Luminus PDF-download-URL')
    ap.add_argument('--output',default='gas_luminus_index.json')
    args=ap.parse_args()
    out={'schema_version':1,'bron':'Luminus indexen PDF','status':'NIET_GEVALIDEERD','voor_android_app':False,'geschikt_voor_automatische_jaarprijs':False}
    try:
        if args.pdf:
            data=Path(args.pdf).read_bytes()
            out['bronbestand']=Path(args.pdf).name
        elif args.url:
            import requests
            r=requests.get(args.url,timeout=30,headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status()
            if not r.content.startswith(b'%PDF'):
                raise ValueError('URL levert geen PDF')
            data=r.content
            out['bron_url']=args.url
        else:
            import requests
            with requests.Session() as session:
                download_url = discover_pdf_url(session)
                r = session.get(download_url, timeout=30, headers={'User-Agent':'Mozilla/5.0'})
                r.raise_for_status()
                if not r.content.startswith(b'%PDF'):
                    raise ValueError('Ontdekte URL levert geen PDF')
                data = r.content
                out['bron_url'] = download_url
        hist,forward,tariff,historic_month=parse_pdf(data)
        out.update(status='INDEX_EN_FORWARD_UIT_PDF_GEVONDEN',index='TTF DAH M',tariefmaand=tariff,historische_indexmaand=historic_month,historische_waarde_eur_per_mwh=hist,geschatte_jaarparameter_eur_per_mwh=forward,bronbewijs_consistent=True,jaarprognose_gevalideerd=False)
        out['actueel_voor_huidige_maand'] = tariff == dt.datetime.now(dt.timezone.utc).strftime('%Y-%m')
        if not out['actueel_voor_huidige_maand']:
            out['status'] = 'HISTORISCHE_PDF_GEEN_ACTUELE_INDEX'
            out['reden'] = 'PDF is niet van de huidige kalendermaand'
    except Exception as exc:
        out['reden']=f'{type(exc).__name__}: {exc}'
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out['status'],out.get('reden',''))

if __name__=='__main__':
    main()
