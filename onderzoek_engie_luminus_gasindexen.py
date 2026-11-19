#!/usr/bin/env python3
"""Onderzoek publieke ENGIE/Luminus-bronnen zonder indexwaarden te verzinnen.

Schrijft uitsluitend bron-diagnostiek; geen gevalideerde marktwaarden of jaarprijzen.
"""
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import requests

OUT = Path('gas_index_brononderzoek.json')
SOURCES = {
    'ENGIE Flow Gas': {
        'index': 'ZTPDAM (Heren)',
        'url': 'https://www.engie.be/nl/energie/elektriciteit-gas/prijzen-voorwaarden/indexatieparameters/indexatieparameters-gas',
        'terms': ['ZTPDAM', 'ZTP DAM', 'Heren'],
    },
    'Luminus BasicFlex Online Gas': {
        'index': 'TTF DAH M',
        'url': 'https://my.luminusbusiness.be/market-info/en/indices-overview/',
        'terms': ['TTF DAH', 'TTFDAH', 'Day Ahead'],
    },
}

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignore += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.ignore:
            self.ignore -= 1
    def handle_data(self, data):
        if not self.ignore and data.strip():
            self.parts.append(data.strip())

def inspect_source(source, session):
    result = {'bron_url': source['url'], 'index': source['index'],
              'status': 'GEEN_GEVERIFIEERDE_INDEXWAARDE',
              'historische_index_gevalideerd': False,
              'jaarprognose_gevalideerd': False,
              'geschikt_voor_automatische_jaarprijs': False}
    try:
        r = session.get(source['url'], timeout=25, headers={'User-Agent': 'EerlijkeEnergie/1.0 (index-brononderzoek)'})
        result['http_status'] = r.status_code
        result['uiteindelijke_url'] = r.url
        result['content_type'] = r.headers.get('Content-Type', '')
        r.raise_for_status()
        if 'html' not in result['content_type'].lower():
            result['status'] = 'BRON_GEEN_HTML_HANDMATIGE_INSPECTIE'
            return result
        parser = TextExtractor()
        parser.feed(r.text)
        text = ' '.join(parser.parts)
        hits = []
        for term in source['terms']:
            for m in list(re.finditer(re.escape(term), text, flags=re.IGNORECASE))[:5]:
                snippet = re.sub(r'\s+', ' ', text[max(0, m.start()-100):m.end()+180]).strip()
                if snippet not in hits:
                    hits.append(snippet)
        result['index_bronfragmenten'] = hits[:12]
        result['status'] = 'INDEXTERM_GEVONDEN_NOG_GEEN_WAARDEVALIDATIE' if hits else 'INDEXTERM_NIET_IN_HTML_GEVONDEN'
    except requests.RequestException as exc:
        result['status'] = 'BRON_NIET_BEREIKBAAR'
        result['fout'] = f'{type(exc).__name__}: {str(exc)[:240]}'
    except Exception as exc:
        result['status'] = 'BRONFORMAAT_NIET_VERWERKT'
        result['fout'] = f'{type(exc).__name__}: {str(exc)[:240]}'
    return result

def main():
    with requests.Session() as session:
        contracts = {name: inspect_source(source, session) for name, source in SOURCES.items()}
    report = {
        'schema_version': 1,
        'gegenereerd_op_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'BRONONDERZOEK_GEEN_INDEXVALIDATIE',
        'voor_android_app': False,
        'contracten': contracts,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, entry in contracts.items():
        print(f'{name}: {entry["status"]}')
    print(f'Rapport: {OUT}')

if __name__ == '__main__':
    main()
