#!/usr/bin/env python3
"""Bewijsrapport gasindexen uit gehashte archief-PDF's; geen prijsgoedkeuring."""
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pdfplumber
import requests

BRON = Path('gas_archiefformules_vergelijking.json')
UITVOER = Path('gas_indexwaarden_bewijs.json')
INDEX = re.compile(r'\b(?:ZTP\s*DAM|ZTPDAM|ZTP\s*RLP|ZTPRLPM|TTF\s*DAH\s*M|TTFDAHM|TTF\s*RLP)\b', re.I)
GETAL = re.compile(r'(?<![\d.,])\d{1,3}(?:[.,]\d{1,4})?\s*(?:€\s*/\s*MWh|EUR\s*/\s*MWh|c€\s*/\s*kWh)', re.I)
MAAND = re.compile(r'\b(?:januari|februari|maart|april|mei|juni|juli|augustus|september|oktober|november|december)\s+20\d\d\b', re.I)


def bewijs_uit_pdf(pdf):
    """Neem tekstfragmenten op, zonder bedragen automatisch aan een index te koppelen."""
    indexregels = []
    waarderegels = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for nr, pagina in enumerate(doc.pages, 1):
            regels = (pagina.extract_text(layout=False) or '').splitlines()
            for i, regel in enumerate(regels):
                if INDEX.search(regel):
                    context = ' '.join(regels[max(0, i-1):min(len(regels), i+2)])
                    indexregels.append({'pagina': nr, 'regel': i+1, 'tekst': context[:650]})
                context = ' '.join(regels[max(0, i-2):min(len(regels), i+3)])
                if GETAL.search(context) and (INDEX.search(context) or MAAND.search(context) or
                                             re.search(r'index|parameter|waarde|geschat', context, re.I)):
                    waarderegels.append({'pagina': nr, 'regel': i+1, 'tekst': context[:650],
                                        'getallen_met_eenheid': GETAL.findall(context)})
    return indexregels[:45], waarderegels[:35]


def inspecteer(naam, info, sessie):
    result = {'tariefmaand': info.get('tariefmaand_archief'),
              'status': 'NIET_GEVERIFIEERD', 'indexwaarde_gevalideerd': False,
              'geschikt_voor_automatische_jaarprijs': False,
              'index_bronregels': [], 'waarde_bronregels': []}
    if info.get('status') != 'formule_gelijk_aan_referentie' or info.get('formule_gelijk') is not True:
        result['reden'] = 'formule_niet_goedgekeurd'
        return result
    url = info.get('pdf_url', '')
    parsed = urlparse(url)
    sha = parse_qs(parsed.query).get('pdf', [''])[0].lower()
    if parsed.scheme != 'https' or parsed.hostname != 'energieplatform-vlaanderen.be' or not re.fullmatch(r'[0-9a-f]{64}', sha):
        result['reden'] = 'ongeldige_bron_url'
        return result
    try:
        resp = sessie.get(url, timeout=45)
        resp.raise_for_status()
        pdf = resp.content
        if not pdf.startswith(b'%PDF-') or len(pdf) > 15_000_000:
            raise ValueError('ongeldige_pdf')
        digest = hashlib.sha256(pdf).hexdigest()
        if digest != sha or digest != info.get('sha256'):
            raise ValueError('sha256_verschilt')
        indexregels, waarderegels = bewijs_uit_pdf(pdf)
        result.update({'pdf_sha256': digest, 'index_bronregels': indexregels,
                       'waarde_bronregels': waarderegels,
                       'formule_uit_archief': info.get('formule_gevonden'),
                       'status': 'BRONREGELS_GEVONDEN_HANDMATIGE_CONTROLE' if indexregels else 'INDEX_NIET_GEVONDEN',
                       'reden': 'Maandwaarde, jaarparameter, eenheden en definitie afzonderlijk controleren; geen automatische goedkeuring'})
    except (requests.RequestException, ValueError, Exception) as exc:
        result['reden'] = 'pdf_controle_mislukt: ' + str(exc)[:180]
    return result


def main():
    data = json.loads(BRON.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Ongeldig gas_archiefformules_vergelijking.json')
    rapport = {'schema_version': 1, 'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
               'bron': BRON.name, 'status': 'INDEX_BEWIJS_GEEN_PRIJSVALIDATIE',
               'voor_android_app': False,
               'waarschuwing': 'Indexregels zijn bronbewijs; niet automatisch bruikbaar voor jaarprijs of Android.',
               'contracten': {}}
    with requests.Session() as sessie:
        sessie.headers['User-Agent'] = 'EerlijkeEnergie-GasIndexBewijs/1.0'
        for naam, info in data['contracten'].items():
            rapport['contracten'][naam] = inspecteer(naam, info, sessie)
            print(naam, rapport['contracten'][naam]['status'])
    temp = UITVOER.with_suffix('.json.tmp')
    temp.write_text(json.dumps(rapport, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    temp.replace(UITVOER)
    print('Rapport geschreven:', UITVOER)

if __name__ == '__main__':
    main()
