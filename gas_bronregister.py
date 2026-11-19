#!/usr/bin/env python3
"""Monitor vijf bestaande gas-PDF-bronnen op wijzigingen.

Leest het vorige gas_bronregister.json als referentie. Ontdekt geen nieuwe
archief-URL's en valideert geen prijzen. Wijzigt geen andere bestanden.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json

import requests

from controle_gas_tariefkaarten import GAS_CONTRACTEN

UITVOER = Path('gas_bronregister.json')
DYNAMISCHE_BRONNEN = {'Ecofix Flexy Online', 'TotalEnergies myEssential Variabel Gas'}


def vorig_register() -> dict:
    if not UITVOER.exists():
        return {}
    try:
        data = json.loads(UITVOER.read_text(encoding='utf-8'))
        if not isinstance(data.get('contracten'), dict):
            raise ValueError('contracten ontbreekt')
        return data['contracten']
    except (OSError, ValueError, TypeError) as fout:
        raise SystemExit(f'FOUT: bestaand bronregister ongeldig: {fout}')


def controleer_bron(naam: str, url: str, vorig: dict) -> dict:
    dynamisch = naam in DYNAMISCHE_BRONNEN
    resultaat = {
        'bron_url': url,
        'bron_type': 'dynamische_pdf_link' if dynamisch else 'vast_archiefdocument',
        'download_status': 'fout',
        'sha256': vorig.get('sha256'),
        'pdf_bytes': vorig.get('pdf_bytes'),
        'tariefmaand': None,
        'geldigheid_status': 'niet_vastgesteld',
        'automatisch_nieuwe_link_gevonden': False,
        'wijziging_status': 'download_mislukt',
        'vorige_sha256': vorig.get('sha256'),
    }
    try:
        antwoord = requests.get(url, timeout=45, headers={'User-Agent': 'EerlijkeEnergie/1.0'})
        antwoord.raise_for_status()
        inhoud = antwoord.content
        if len(inhoud) > 15_000_000 or not inhoud.startswith(b'%PDF-'):
            raise ValueError('Geen PDF of PDF groter dan 15 MB')
        nieuw = sha256(inhoud).hexdigest()
        oud = vorig.get('sha256') if vorig.get('bron_url') == url else None
        resultaat['download_status'] = 'pdf_bereikbaar'
        resultaat['sha256'] = nieuw
        resultaat['pdf_bytes'] = len(inhoud)
        if oud is None:
            resultaat['wijziging_status'] = 'eerste_meting_of_nieuwe_url'
        elif nieuw == oud:
            resultaat['wijziging_status'] = 'ongewijzigd'
        else:
            resultaat['wijziging_status'] = 'pdf_gewijzigd'
            resultaat['vorige_sha256'] = oud
        if not dynamisch and resultaat['wijziging_status'] == 'ongewijzigd':
            resultaat['opmerking'] = 'Vast archief: controleer een nieuwe maand via een nieuwe bron-URL'
    except (requests.RequestException, ValueError) as fout:
        resultaat['fout'] = str(fout)[:250]
        resultaat['opmerking'] = 'Vorige bekende hash behouden; geen nieuwe prijsgegevens publiceren'
    return resultaat


def main() -> None:
    vorige = vorig_register()
    contracten = {
        naam: controleer_bron(naam, gegevens['url'], vorige.get(naam, {}))
        for naam, gegevens in GAS_CONTRACTEN.items()
    }
    payload = {
        'schema_version': 1,
        'gecontroleerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'bronmonitoring_geen_prijsvalidatie',
        'waarschuwing': (
            'PDF-wijziging is geen bewijs van een nieuwe tariefmaand of correcte prijzen. '
            'Vaste archief-URL’s worden niet automatisch vernieuwd.'
        ),
        'contracten': contracten,
    }
    tijdelijk = UITVOER.with_suffix('.json.tmp')
    tijdelijk.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tijdelijk.replace(UITVOER)
    for naam, gegevens in contracten.items():
        status = gegevens['wijziging_status']
        print(f'{naam}: {status} ({gegevens["download_status"]})')
        if status == 'pdf_gewijzigd':
            print(f'  LET OP: PDF-inhoud gewijzigd; tariefkaart handmatig of afzonderlijk valideren')
        if status == 'download_mislukt':
            print(f'  WAARSCHUWING: {gegevens.get("fout", "download mislukt")}')
    print(f'Bronregister geschreven: {UITVOER}')


if __name__ == '__main__':
    main()
