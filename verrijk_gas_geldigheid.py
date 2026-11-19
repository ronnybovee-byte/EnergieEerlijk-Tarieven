#!/usr/bin/env python3
"""Verrijk gevalideerde gasformules met aantoonbare tariefkaartmaanden.

Een gevonden datum is niet automatisch een geldigheidsmaand. Bij twijfel
wordt geen maand toegekend. Dit script wijzigt geen prijsformules.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from controle_gas_tariefkaarten import GAS_CONTRACTEN, lees_pdf

BESTAND = Path("gas_gevalideerde_formules.json")
MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4,
    "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}
MAAND_NAMEN = "|".join(MAANDEN)

# Alleen contexten die expliciet op contracten of tariefkaartprijzen slaan.
CONTRACT_PERIODE = re.compile(
    rf"prijzen\s+(?:aardgas\s+)?voor\s+contracten\s+afgesloten\s+in\s+"
    rf"(?P<maand>{MAAND_NAMEN})\s+(?P<jaar>20\d{{2}})",
    re.IGNORECASE,
)
CONTRACT_DATUMBEREIK = re.compile(
    r"geldig\s+voor\s+elk\s+getekend\s+contract\s+tussen\s+"
    r"(?P<dag1>\d{1,2})/(?P<maand1>\d{1,2})/(?P<jaar1>20\d{2})\s+en\s+"
    r"(?P<dag2>\d{1,2})/(?P<maand2>\d{1,2})/(?P<jaar2>20\d{2})",
    re.IGNORECASE,
)


def vind_tariefmaand(tekst: str) -> tuple[str | None, str]:
    # PDF-extractie kan regels midden in een zin afbreken.
    vlak = re.sub(r"\s+", " ", tekst).strip()
    kandidaten = set()
    for match in CONTRACT_PERIODE.finditer(vlak):
        maand = MAANDEN[match.group("maand").lower()]
        kandidaten.add(f"{int(match.group('jaar')):04d}-{maand:02d}")

    for match in CONTRACT_DATUMBEREIK.finditer(vlak):
        m1, m2 = int(match.group("maand1")), int(match.group("maand2"))
        j1, j2 = int(match.group("jaar1")), int(match.group("jaar2"))
        d1, d2 = int(match.group("dag1")), int(match.group("dag2"))
        if j1 == j2 and m1 == m2 and 1 <= m1 <= 12 and d1 == 1 and 28 <= d2 <= 31:
            kandidaten.add(f"{j1:04d}-{m1:02d}")

    if len(kandidaten) == 1:
        return next(iter(kandidaten)), "expliciete_contractperiode_in_pdf"
    if len(kandidaten) > 1:
        return None, "tegenstrijdige_contractperiodes"
    return None, "geen_eenduidige_contractperiode"


def lees_bron(naam: str, url: str) -> str:
    antwoord = requests.get(
        url, timeout=45, headers={"User-Agent": "EerlijkeEnergie/1.0"}
    )
    antwoord.raise_for_status()
    if not antwoord.content.startswith(b"%PDF-"):
        raise ValueError(f"Geen PDF voor {naam}")
    if len(antwoord.content) > 15_000_000:
        raise ValueError(f"PDF te groot voor {naam}")
    tekst, _ = lees_pdf(antwoord.content)
    if not tekst.strip():
        raise ValueError(f"Geen PDF-tekst voor {naam}")
    return tekst


def main() -> None:
    if not BESTAND.is_file():
        raise SystemExit("FOUT: gas-JSON ontbreekt")
    gegevens = json.loads(BESTAND.read_text(encoding="utf-8"))
    contracten = gegevens.get("contracten")
    if not isinstance(contracten, dict) or not contracten:
        raise SystemExit("FOUT: geen gevalideerde contracten")

    huidige_maand = datetime.now(timezone.utc).strftime("%Y-%m")
    for naam, formule in contracten.items():
        if naam not in GAS_CONTRACTEN or not isinstance(formule, dict):
            raise SystemExit(f"FOUT: onbekend of ongeldig contract: {naam}")
        url = GAS_CONTRACTEN[naam]["url"]
        # Een mislukte download mag geen schijnbaar actuele publicatie opleveren.
        tekst = lees_bron(naam, url)
        maand, reden = vind_tariefmaand(tekst)
        formule["bron_url"] = url
        formule["tariefmaand"] = maand
        formule["geldigheid_status"] = (
            "contractperiode_herkend" if maand else "nog_te_bevestigen"
        )
        formule["geldigheid_bewijs"] = reden
        formule["is_huidige_maand"] = bool(maand and maand == huidige_maand)
        print(f"{naam}: maand={maand or 'onbekend'}, status={reden}")

    gegevens["laatst_gecontroleerd_utc"] = datetime.now(timezone.utc).isoformat()
    gegevens["waarschuwing"] = (
        "Geldigheidsmaanden zijn alleen herkend bij expliciete contractperiodes. "
        "Dit bevestigt geen actuele bronbeschikbaarheid, indexdefinitie, "
        "indexwaarde, vaste vergoeding of totale jaarprijs."
    )
    tijdelijk = BESTAND.with_name(BESTAND.name + ".tmp")
    try:
        tijdelijk.write_text(
            json.dumps(gegevens, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tijdelijk.replace(BESTAND)
    finally:
        tijdelijk.unlink(missing_ok=True)
    print(f"Verrijkt: {len(contracten)} gascontracten")


if __name__ == "__main__":
    main()
