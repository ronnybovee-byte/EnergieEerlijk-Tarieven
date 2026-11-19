
#!/usr/bin/env python3
"""Onderzoek de geldigheidsmaand van gastariefkaarten."""

from datetime import datetime, timezone
import re

import requests

from controle_gas_tariefkaarten import GAS_CONTRACTEN, lees_pdf


MAANDEN = (
    "januari", "februari", "maart", "april",
    "mei", "juni", "juli", "augustus",
    "september", "oktober", "november", "december"
)


def zoek_datums(tekst):
    patronen = [
        r"\b(?:geldig|van toepassing|tariefkaart|prijzen)"
        r"[^\n]{0,100}",

        r"\b(?:"
        + "|".join(MAANDEN)
        + r")\s+20\d{2}\b",

        r"\b(?:0?[1-9]|1[0-2])[/.-]20\d{2}\b",
    ]

    resultaten = []

    for patroon in patronen:
        for match in re.finditer(
            patroon, tekst, re.IGNORECASE
        ):
            waarde = match.group(0).strip()
            if waarde not in resultaten:
                resultaten.append(waarde)

    return resultaten[:20]


def main():
    vandaag = datetime.now(timezone.utc)

    print("Controle geldigheidsmaand gastariefkaarten")
    print("Uitgevoerd:", vandaag.isoformat())

    for naam, gegevens in GAS_CONTRACTEN.items():
        print("\nCONTRACT:", naam)

        try:
            response = requests.get(
                gegevens["url"],
                timeout=45,
                headers={"User-Agent": "EerlijkeEnergie/1.0"},
            )
            response.raise_for_status()

            if not response.content.startswith(b"%PDF-"):
                raise ValueError("Geen geldig PDF-bestand")

            if len(response.content) > 15_000_000:
                raise ValueError("PDF te groot")

            tekst, _ = lees_pdf(response.content)
            datums = zoek_datums(tekst)

            if datums:
                for datum in datums:
                    print("DATUMVERMELDING:", datum)
            else:
                print("GEEN DATUM GEVONDEN")

            print("STATUS: GELDIGHEID NOG NIET BEVESTIGD")

        except Exception as fout:
            print("FOUT:", fout)


if __name__ == "__main__":
    main()
