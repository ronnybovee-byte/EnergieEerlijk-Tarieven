#!/usr/bin/env python3
"""Veilige publicatiepoort voor gas: uitsluitend status, nooit onvolledige jaarprijzen."""
import json
from pathlib import Path
from datetime import datetime, timezone

SOURCE = Path('gas_archiefformules_vergelijking.json')
OUTPUT = Path('gas_app_publicatie_status.json')
FIXED = Path('gas_vaste_vergoedingen_validatie.json')
REQUIRED = {'ENGIE Flow Gas', 'Luminus BasicFlex Online Gas', 'OCTA+ Boost Flex Gas'}


def check(data, fixed):
    rows = data.get('contracten', {})
    fixed_rows = fixed.get('contracten', {})
    result = {}
    for name in sorted(REQUIRED):
        item = rows.get(name)
        issues = []
        if not isinstance(item, dict):
            issues.append('Geen vergelijking beschikbaar')
        else:
            if item.get('tariefmaand_archief') != '2026-11':
                issues.append('Tariefmaand niet bevestigd als 2026-11')
            if item.get('status') != 'formule_gelijk_aan_referentie' or item.get('formule_gelijk') is not True:
                issues.append('Formulevergelijking niet geslaagd')
            if not item.get('contract_herkend') or not item.get('maand_vermeld'):
                issues.append('Contract of maand niet herkend')
            if item.get('formule_gevonden') != item.get('referentieformule'):
                issues.append('Formule wijkt af van referentie')
        # Deze gegevens zijn NIET aanwezig in het bronrapport. Nooit automatisch goedkeuren.
        issues.append('Contractuele indexwaarde en eenheid niet onafhankelijk geverifieerd')
        fixed_item = fixed_rows.get(name, {})
        if fixed.get('referentiemaand') != '2026-11' or fixed_item.get('vaste_vergoeding_volledig_gevalideerd') is not True:
            issues.append('Vaste leveranciersvergoeding niet volledig geverifieerd')
        if fixed_item.get('voorwaarden_automatisch_gevalideerd') is not True:
            issues.append('Contractvoorwaarden niet automatisch gevalideerd')
        issues.append('Volledige netkosten, accijnzen en btw niet als jaarprijs geverifieerd')
        result[name] = {
            'formule_gecontroleerd': not any(x for x in issues if x.startswith(('Geen vergelijking','Tariefmaand','Formulevergelijking','Contract of','Formule wijkt'))),
            'geschikt_voor_automatische_jaarprijs': False,
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
    report = {
        'schema_version': 1,
        'gegenereerd_op_utc': datetime.now(timezone.utc).isoformat(),
        'bron': SOURCE.name,
        'status': 'ALLEEN_FORMULECONTROLE_GEEN_AUTOMATISCHE_JAARPRIJZEN',
        'voor_android_app': False,
        'contracten': check(data, fixed),
    }
    OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Rapport geschreven: {OUTPUT}')
    for name, item in report['contracten'].items():
        print(f'{name}: formule={item["formule_gecontroleerd"]}; automatische jaarprijs=GEBLOKKEERD')


if __name__ == '__main__':
    main()
