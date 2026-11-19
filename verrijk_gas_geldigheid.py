
#!/usr/bin/env python3
"""Voeg gecontroleerde bron- en geldigheidsinformatie toe aan gas-JSON."""

import json
from datetime import datetime, timezone
from pathlib import Path

from controle_gas_tariefkaarten import GAS_CONTRACTEN

BESTAND = Path("gas_gevalideerde_formules.json")

# Alleen periodes waarvan de contractcontext duidelijk is.
BEVESTIGDE_PERIODES = {
    "Ecofix Flexy Online": "2026-11",
    "ENGIE Flow Gas": "2026-11",
    "OCTA+ Boost Flex Gas": "2026-11",
}

def main():
    if not BESTAND.exists():
        raise SystemExit("FOUT: gas-JSON ontbreekt")

    gegevens = json.loads(BESTAND.read_text(encoding="utf-8"))
    contracten = gegevens.get("contracten", {})

    if not contracten:
        raise SystemExit("FOUT: geen gevalideerde contracten")

    for naam, formule in contracten.items():
        if naam not in GAS_CONTRACTEN:
            raise SystemExit(f"Onbekend contract: {naam}")

        formule["bron_url"] = GAS_CONTRACTEN[naam]["url"]
        formule["tariefmaand"] = BEVESTIGDE_PERIODES.get(naam)
        formule["geldigheid_status"] = (
            "historische_periode_bevestigd"
            if naam in BEVESTIGDE_PERIODES
            else "nog_te_bevestigen"
        )

    gegevens["laatst_gecontroleerd_utc"] = (
        datetime.now(timezone.utc).isoformat()
    )
    gegevens["waarschuwing"] = (
        "Formules gecontroleerd tegen bron-PDF's. "
        "Historische tariefmaanden zijn geen bewijs van actuele prijzen. "
        "Indexwaarden, vaste vergoedingen en jaarprijzen "
        "zijn nog niet volledig gevalideerd."
    )

    BESTAND.write_text(
        json.dumps(
            gegevens,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Verrijkt: {len(contracten)} gascontracten")

if __name__ == "__main__":
    main()
