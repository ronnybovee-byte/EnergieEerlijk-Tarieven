
#!/usr/bin/env python3
"""Controle van officiële gastariefkaarten voor Eerlijke Energie."""

from io import BytesIO
from datetime import datetime
import sys

import requests
import pdfplumber

GAS_CONTRACTEN = {
    "Ecofix Flexy Online": {
        "url": (
            "https://portal.ecofixgp.be/docs/prices/current/"
            "GAS_Ecofix_Flexy_Online_NL.pdf"
        ),
        "zoektermen": ["Ecofix", "Flexy", "2026"],
    },
}


def controleer_tariefkaart(naam, gegevens):
    print(f"\nControle: {naam}")

    response = requests.get(
        gegevens["url"],
        timeout=30,
        headers={"User-Agent": "EerlijkeEnergie/1.0"},
    )
    response.raise_for_status()

    if not response.content.startswith(b"%PDF-"):
        raise ValueError("Download is geen geldig PDF-bestand")

    with pdfplumber.open(BytesIO(response.content)) as pdf:
        tekst = "\n".join(
            pagina.extract_text() or ""
            for pagina in pdf.pages
        )

    if not tekst.strip():
        raise ValueError("Geen leesbare tekst in de tariefkaart")

    ontbrekend = [
        term
        for term in gegevens["zoektermen"]
        if term.lower() not in tekst.lower()
    ]

    if ontbrekend:
        raise ValueError(
            "Ontbrekende herkenningswoorden: "
            + ", ".join(ontbrekend)
        )

    print(f"PDF gedownload: {len(response.content)} bytes")
    print("Herkenningswoorden: OK")
    print("Tariefkaart leesbaar: OK")
    print("Prijsformule: nog niet gevalideerd")
    print("STATUS: DOCUMENTCONTROLE GESLAAGD")


def main():
    print("Eerlijke Energie - controle gastariefkaarten")
    print("Controle uitgevoerd:", datetime.now().isoformat())

    fouten = 0

    for naam, gegevens in GAS_CONTRACTEN.items():
        try:
            controleer_tariefkaart(naam, gegevens)
        except Exception as fout:
            fouten += 1
            print(f"FOUT bij {naam}: {fout}")

    if fouten:
        print(f"\nMISLUKT: {fouten} tariefkaart(en)")
        return 1

    print("\nGESLAAGD: alle gastariefkaarten bereikbaar en leesbaar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
