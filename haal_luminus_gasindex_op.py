#!/usr/bin/env python3
"""Conservatieve Luminus TTFDAHM extractie; wijzigt bestaande JSON niet."""
import argparse
import datetime as dt
import io
import json
import re
from pathlib import Path

import pdfplumber

MONTHS = ['Januari','Februari','Maart','April','Mei','Juni','Juli','Augustus','September','Oktober','November','December']

def parse_pdf(data):
    with pdfplumber.open(io.BytesIO(data)) as doc:
        page = doc.pages[0]
        words = page.extract_words()
        text = page.extract_text() or ''
    if 'TTFDAHM' not in text.replace(' ', ''):
        raise ValueError('TTFDAHM niet aanwezig')
    m = re.search(r'November\s+2026', text, re.I)
    if not m:
        raise ValueError('Tariefmaand november 2026 niet bevestigd; geen automatische goedkeuring')
    # Layout: BasicFlex TTFDAHM-tabel, pagina 1, gasgedeelte, x=230..385.
    region = [w for w in words if 225 <= w['x0'] <= 385 and w['top'] > 330]
    def row(label):
        labels = [w for w in region if w['text'].casefold() == label.casefold()]
        if len(labels) != 1:
            raise ValueError(f'Rij {label} niet eenduidig: {len(labels)}')
        y = labels[0]['top']
        return sorted([w for w in region if abs(w['top']-y)<2.0 and w['x0']>labels[0]['x0']+30],key=lambda w:w['x0'])
    def number(s):
        if not re.fullmatch(r'\d{1,3},\d{3}',s):
            raise ValueError('Ongeldig indexgetal: '+s)
        return float(s.replace(',','.'))
    oct_values = [number(w['text']) for w in row('Oktober') if re.fullmatch(r'\d{1,3},\d{3}',w['text'])]
    if len(oct_values)!=3:
        raise ValueError(f'Oktober heeft {len(oct_values)} waarden, verwacht 3')
    fw = [w for w in region if w['text']=='Forward*' and w['top']>480]
    if len(fw)!=1:
        raise ValueError('Forwardrij niet eenduidig')
    fvals = [w for w in region if abs(w['top']-fw[0]['top'])<2 and w['x0']>fw[0]['x1'] and re.fullmatch(r'\d{1,3},\d{3}',w['text'])]
    if len(fvals)!=1:
        raise ValueError('Forwardwaarde niet eenduidig')
    hist=oct_values[2]; forward=number(fvals[0]['text'])
    if not (0<hist<1000 and 0<forward<1000):
        raise ValueError('Index buiten controlebereik')
    return hist,forward

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
            raise ValueError('Geen directe PDF-URL ingesteld; gebruik --url of --pdf')
        hist,forward=parse_pdf(data)
        out.update(status='INDEX_EN_FORWARD_UIT_PDF_GEVONDEN',index='TTF DAH M',tariefmaand='2026-11',historische_indexmaand='2026-10',historische_waarde_eur_per_mwh=hist,geschatte_jaarparameter_eur_per_mwh=forward,bronbewijs_consistent=True,jaarprognose_gevalideerd=False)
    except Exception as exc:
        out['reden']=f'{type(exc).__name__}: {exc}'
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out['status'],out.get('reden',''))

if __name__=='__main__':
    main()
