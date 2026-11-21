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
import pymupdf as fitz
import pytesseract
from PIL import Image, ImageOps
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from controle_gas_tariefkaarten import lees_pdf

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
    
def lees_totalenergies_prijs(pdf):
    prijzen = set()

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for pagina in doc.pages:
            tekst = ' '.join((pagina.extract_text() or '').split())

            if 'TTF_M_RLP' not in tekst:
                continue

            if not re.search(r'BTW\s+6\s*%\s*inbegrepen', tekst, re.I):
                continue

            if 'geschat voor de energieafname' not in tekst:
                continue

            for tabel in pagina.extract_tables():
                if len(tabel) != 3:
                    continue

                if not all(len(rij) == 1 for rij in tabel):
                    continue

                label = ' '.join((tabel[0][0] or '').split())
                waarde = (tabel[1][0] or '').strip()
                formule = tabel[2][0] or ''

                if not label.startswith('Verbruik'):
                    continue

                if 'c€/kWh' not in label:
                    continue

                if 'TTF_M_RLP' not in formule:
                    continue

                if re.fullmatch(r'\d+[,.]\d{2}', waarde):
                    prijs = float(waarde.replace(',', '.'))
                    if prijs > 0:
                        prijzen.add(prijs)

    return prijzen.pop() if len(prijzen) == 1 else None
def lees_ecofix_prijs(pdf):
    tekst, _ = lees_pdf(pdf)
    tekst = ' '.join(tekst.split())

    jaarprijs_ok = bool(re.search(
        r'verwachte\s+jaarprijs', tekst, re.I
    ))

    btw_ok = bool(re.search(
        r'incl(?:usief)?\.?\s*6\s*%\s*btw',
        tekst, re.I
    ))
    if not jaarprijs_ok:
        with fitz.open(stream=pdf, filetype='pdf') as doc:
            pagina = doc[0]
            breedte = pagina.rect.width
            hoogte = pagina.rect.height

            uitsnede = fitz.Rect(
                breedte * 0.79,
                hoogte * 0.543,
                breedte * 0.898,
                hoogte * 0.555
            )

            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(8, 8),
                clip=uitsnede,
                alpha=False
            )

            afbeelding = Image.frombytes(
                'RGB', (pix.width, pix.height), pix.samples
            )

            afbeelding = ImageOps.autocontrast(
                ImageOps.invert(afbeelding.convert('L'))
            )

            afbeelding = ImageOps.expand(
                afbeelding, border=20, fill=255
            )

            detailtekst = pytesseract.image_to_string(
                afbeelding, lang='nld+eng', config='--psm 7'
            )
            
            jaarprijs_ok = bool(re.search(
                r'verwachte\s+jaar\s*prijs',
                detailtekst, re.I
            ))

            print('ECOFIX detail-OCR:', detailtekst)
    print('ECOFIX jaarprijslabel:', jaarprijs_ok)
    print('ECOFIX btw-label:', btw_ok)
    print('ECOFIX OCR:', tekst[:1800])

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        pagina = doc.pages[0]

        bedragen = []

        for w in pagina.extract_words():
            if re.fullmatch(
                r'\d{1,4}[,.]\d{2}', w['text']
            ):
                x = w['x0'] / pagina.width
                y = w['top'] / pagina.height

                print(
                    'ECOFIX bedrag:', w['text'],
                    'x:', round(x, 5),
                    'y:', round(y, 5)
                )

                if 0.59 < x < 0.66 and 0.54 < y < 0.56:
                    bedragen.append(w)

        if jaarprijs_ok and btw_ok and len(bedragen) == 1:
            prijs = float(
                bedragen[0]['text'].replace(',', '.')
            )
            if prijs > 0:
                return prijs

    return None
def lees_engie_jaarparameter(indexregels, waarderegels):
    waarden = set()

    for regel in indexregels + waarderegels:
        tekst = regel.get('tekst', '')

        patroon = (
            r'De geschatte jaarlijkse parameter\s+'
            r'ZTPDAM\s*\(Heren\)\s+bedraagt'
            r'.{0,180}?'
            r'(\d{1,3}[,.]\d{1,4})\s*'
            r'€/MWh\s+voor deze maand'
        )

        for match in re.finditer(patroon, tekst, re.I):
            waarde = float(match.group(1).replace(',', '.'))
            if 0 < waarde <= 1000:
                waarden.add(waarde)

    return waarden.pop() if len(waarden) == 1 else None
def inspecteer(naam, info, sessie):
    result = {'tariefmaand': info.get('tariefmaand_archief'),
              'status': 'NIET_GEVERIFIEERD', 'indexwaarde_gevalideerd': False,
              'geschikt_voor_automatische_jaarprijs': False,
              'index_bronregels': [], 'waarde_bronregels': []}
    if (
        info.get('formule_technisch_gevalideerd') is not True
        or info.get('referentie_index_behouden') is not True
        or info.get('tariefmaand_archief') != datetime.now(timezone.utc).strftime('%Y-%m')
    ):
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
        if naam == 'ENGIE Flow Gas':
            jaarparameter = lees_engie_jaarparameter(
                indexregels, waarderegels
            )
            if jaarparameter is not None:
                result['geschatte_jaarparameter_eur_per_mwh'] = jaarparameter
        if naam == 'TotalEnergies myEssential Variabel Gas':
            prijs = lees_totalenergies_prijs(pdf)
            if prijs is not None:
                result['geschatte_energieprijs_ct_per_kwh_incl_btw'] = prijs
        if naam == 'Ecofix Flexy Online':
            prijs = lees_ecofix_prijs(pdf)
            if prijs is not None:
                result['geschatte_energieprijs_ct_per_kwh_incl_btw'] = prijs
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
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(('GET',))
        )
        sessie.mount('https://', HTTPAdapter(max_retries=retry))
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
