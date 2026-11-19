#!/usr/bin/env python3
"""Inventariseer bekende gas-PDF-bronnen zonder bestaande prijsfeeds te wijzigen.

Dit is bronmonitoring, GEEN automatische ontdekking van nieuwe tariefkaarten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re

import requests

from controle_gas_tariefkaarten import GAS_CONTRACTEN

UITVOER = Path('gas_bronregister.json')
DYNAMISCHE_BRONNEN = {'Ecofix Flexy Online', 'TotalEnergies myEssential Variabel Gas'}


def controleer_bron(naam: str, url: str) -> dict:
    resultaat = {
        'bron_url': url,
        'bron_type': 'dynamische_pdf_link' if naam in DYNAMISCHE_BRONNEN else 'vast_archiefdocument',
        'download_status': 'fout',
        'sha256': None,
        'pdf_bytes': None,
        'tariefmaand': None,
        'geldigheid_status': 'niet_vastgesteld',
        'automatisch_nieuwe_link_gevonden': False,
    }
    try:
        antwoord = requests.get(url, timeout=45, headers={'User-Agent': 'EerlijkeEnergie/1.0'})
        antwoord.raise_for_status()
        inhoud = antwoord.content
        if len(inhoud) > 15_000_000 or not inhoud.startswith(b'%PDF-'):
            raise ValueError('Geen PDF of PDF groter dan 15 MB')
        resultaat['download_status'] = 'pdf_bereikbaar'
        resultaat['sha256'] = sha256(inhoud).hexdigest()
        resultaat['pdf_bytes'] = len(inhoud)
    except (requests.RequestException, ValueError) as fout:
        resultaat['fout'] = str(fout)[:250]
    return resultaat


def main() -> None:
    nu = datetime.now(timezone.utc).isoformat()
    contracten = {
        naam: controleer_bron(naam, gegevens['url'])
        for naam, gegevens in GAS_CONTRACTEN.items()
    }
    payload = {
        'schema_version': 1,
        'gecontroleerd_op_utc': nu,
        'status': 'broninventaris_geen_prijsvalidatie',
        'waarschuwing': 'Vaste archief-PDFs vernieuwen niet automatisch. Tariefmaand en prijzen zijn niet gevalideerd door dit script.',
        'contracten': contracten,
    }
    tijdelijk = UITVOER.with_suffix('.json.tmp')
    tijdelijk.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tijdelijk.replace(UITVOER)
    for naam, gegevens in contracten.items():
        print(f"{naam}: {gegevens['download_status']} ({gegevens['bron_type']})")
    print(f'Bronregister geschreven: {UITVOER}')


if __name__ == '__main__':
    main()
