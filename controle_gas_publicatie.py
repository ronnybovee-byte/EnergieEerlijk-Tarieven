#!/usr/bin/env python3
"""Resultaatgestuurde bronvrijgave voor gas; persoonlijke kostenberekening in Android."""
import json
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from controle_gas_tariefkaarten import GAS_CONTRACTEN

SOURCE = Path('gas_archiefformules_vergelijking.json')
OUTPUT = Path('gas_app_publicatie_status.json')
FIXED = Path('gas_vaste_vergoedingen_validatie.json')
INDEX = Path('gas_indexen_gecombineerd.json')
REGISTER = Path('gas_bronregister.json')
PRICE = Path('gas_indexwaarden_bewijs.json')

def check(data, fixed, index, month=None, register=None, prices=None):
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    previous = (datetime.strptime(month + "-01", "%Y-%m-%d").date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    rows = data.get('contracten', {})
    fixed_rows = fixed.get('contracten', {})
    index_rows = index.get('contracten', {})
    selected = (register or {}).get('contracten', {})
    result = {}
    for name in sorted(GAS_CONTRACTEN):
        item = rows.get(name)
        issues = []
        if not isinstance(item, dict):
            issues.append('Geen vergelijking beschikbaar')
        else:
            if item.get('tariefmaand_archief') != month:
                issues.append(f"Tariefmaand niet bevestigd als {month}")
            if item.get('status') != 'formule_gelijk_aan_referentie' or item.get('formule_gelijk') is not True:
                issues.append('Formulevergelijking niet geslaagd')
            if not item.get('contract_herkend') or not item.get('maand_vermeld'):
                issues.append('Contract of maand niet herkend')
            if item.get('formule_gevonden') != item.get('referentieformule'):
                issues.append('Formule wijkt af van referentie')
        # Controleer bronresultaten, niet vooraf vastgelegde publicatiestatussen.
        index_item = index_rows.get(name, {})
        price_item = (prices or {}).get('contracten', {}).get(name, {})
        direct_price = price_item.get('geschatte_energieprijs_ct_per_kwh_incl_btw')

        direct_ok = (
            name in (
                'TotalEnergies myEssential Variabel Gas',
                'Ecofix Flexy Online'
            )
            and isinstance(item, dict)
            and item.get('tariefmaand_archief') == month
            and price_item.get('tariefmaand') == month
            and bool(item.get('sha256'))
            and price_item.get('pdf_sha256') == item.get('sha256')
            and price_item.get('formule_uit_archief') == item.get('formule_gevonden')
            and type(direct_price) in (int, float)
            and math.isfinite(direct_price)
            and direct_price > 0
        )
        index_ok = (
            index.get('alle_broncontroles_geslaagd') is True
            and index.get('actueel_voor_huidige_maand') is True
            and index.get('huidige_kalendermaand_utc') == month
            and index_item.get('status') in (
                'HISTORISCHE_BRONWAARDE_GECONTROLEERD',
                'HISTORISCHE_EN_FORWARD_BRONWAARDEN_GECONTROLEERD',
            )
            and index_item.get('historische_indexmaand') == previous
            and isinstance(index_item.get('historische_waarde_eur_per_mwh'), (int, float))
        )
        if not index_ok and not direct_ok:
            issues.append('Historische indexbron niet volledig geverifieerd')
        if not direct_ok and index_item.get('jaarprognose_gevalideerd') is not True:
            issues.append('Jaarprognose index niet gevalideerd')
        fixed_item = fixed_rows.get(name, {})
        if fixed.get('referentiemaand') != month or fixed_item.get('vaste_vergoeding_volledig_gevalideerd') is not True:
            issues.append('Vaste leveranciersvergoeding niet volledig geverifieerd')
        selected_ok = isinstance(selected.get(name), dict)
        if not selected_ok:
            issues.append('Contract ontbreekt in bestaande selectie')
        suitability = fixed_item.get('geschiktheid', {})
        adverse = []
        for key in ('domiciliering_verplicht', 'aandelen_verplicht',
                    'groepsaankoop_verplicht', 'digitale_meter_verplicht',
                    'zonnepanelen_verplicht'):
            if suitability.get(key) == 'ja':
                adverse.append(key)
        for key in ('analoge_meter_toegelaten', 'variabel_contract',
                    'particuliere_klant', 'netgebied'):
            if suitability.get(key) == 'nee':
                adverse.append(key)
        for key, value in suitability.items():
            if value in ('tegenstrijdig', 'conflict'):
                adverse.append(key)
        for key in adverse:
            issues.append('Strijdige contractvoorwaarde: ' + key)
        forward = index_item.get('geschatte_jaarparameter_eur_per_mwh')
        if not direct_ok and (type(forward) not in (int, float) or not math.isfinite(forward) or forward <= 0):
            issues.append('Bruikbare jaarparameter ontbreekt')
        formula = (item or {}).get('formule_gevonden') or {} if isinstance(item, dict) else {}
        normalize = lambda value: ''.join(c for c in str(value).upper() if c.isalnum())
        if not direct_ok and (not normalize(formula.get('index', '')) or normalize(formula.get('index')) != normalize(index_item.get('index', ''))):
            issues.append('Indexnaam wijkt af van tariefformule')
        for key in ('factor', 'toeslag'):
            value = formula.get(key)
            if type(value) not in (int, float) or not math.isfinite(value):
                issues.append('Ongeldige formulecomponent: ' + key)
        try:
            fee = float(fixed_item.get('vast_bedrag_eur_incl_btw_per_jaar'))
            if not math.isfinite(fee) or fee < 0: raise ValueError()
        except (ValueError, TypeError):
            issues.append('Ongeldig vast bedrag')
        result[name] = {
            'rechtstreekse_energieprijs_gevalideerd': direct_ok,
            'geschatte_energieprijs_ct_per_kwh_incl_btw': direct_price if direct_ok and not issues else None,
            'berekeningsmethode': 'rechtstreekse_tariefkaartprijs' if direct_ok else 'indexformule',
            'bestaande_contractselectie': selected_ok,
            'strijdige_contractvoorwaarden': adverse,
            'historische_indexbron_gecontroleerd': index_ok,
            'jaarprognose_gevalideerd': index_item.get('jaarprognose_gevalideerd') is True,
            'formule_gecontroleerd': not any(x for x in issues if x.startswith(('Geen vergelijking','Tariefmaand','Formulevergelijking','Contract of','Formule wijkt'))),
            'geschikt_voor_automatische_jaarprijs': not issues,
            'blokkades': issues,
        }
    return result


def main():
    if not SOURCE.exists():
        raise SystemExit(f'Bronbestand ontbreekt: {SOURCE}')
    data = json.loads(SOURCE.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('contracten'), dict):
        raise SystemExit('Onbekend formaat gas_archiefformules_vergelijking.json')
    if not FIXED.exists():
        raise SystemExit(f'Validatiebestand ontbreekt: {FIXED}')
    fixed = json.loads(FIXED.read_text(encoding='utf-8'))
    if fixed.get('schema_version') != 1 or not isinstance(fixed.get('contracten'), dict):
        raise SystemExit('Onbekend formaat gas_vaste_vergoedingen_validatie.json')
    if not INDEX.exists():
        raise SystemExit(f'Indexbestand ontbreekt: {INDEX}')
    index = json.loads(INDEX.read_text(encoding='utf-8'))
    if index.get('schema_version') != 1 or not isinstance(index.get('contracten'), dict):
        raise SystemExit('Onbekend formaat gas_indexen_gecombineerd.json')
    month = datetime.now(timezone.utc).strftime('%Y-%m')
    if not REGISTER.exists():
        raise SystemExit(f'Gasregister ontbreekt: {REGISTER}')
    register = json.loads(REGISTER.read_text(encoding='utf-8'))
    if register.get('schema_version') != 1 or not isinstance(register.get('contracten'), dict):
        raise SystemExit('Onbekend formaat gas_bronregister.json')

    prices = {}
    if PRICE.exists():
        prices = json.loads(PRICE.read_text(encoding='utf-8'))
        if not isinstance(prices.get('contracten'), dict):
            prices = {}

    contracts = check(data, fixed, index, month, register, prices)
    released = any(c['geschikt_voor_automatische_jaarprijs'] for c in contracts.values())
    report = {
        'schema_version': 1,
        'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'bron': SOURCE.name,
        'aanvullende_bronnen': [FIXED.name, INDEX.name, REGISTER.name, PRICE.name],
        'status': 'BRONVRIJGAVE' if released else 'BRONCONTROLES_GEEN_AUTOMATISCHE_JAARPRIJZEN',
        'referentiemaand': month,
        'kostenberekening': 'Android',
        'voor_android_app': released,
        'contracten': contracts,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Rapport geschreven: {OUTPUT}')
    for name, item in report['contracten'].items():
        print(f'{name}: formule={item["formule_gecontroleerd"]}; automatische jaarprijs={item["geschikt_voor_automatische_jaarprijs"]}')


if __name__ == '__main__':
    main()
