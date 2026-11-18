
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
        "zoektermen": ["November 2026", "9,78", "10,00"],

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
        print(f"\nAantal PDF-pagina's: {len(pdf.pages)}")

        pagina_teksten = []

        for nummer, pagina in enumerate(pdf.pages, start=1):
            pagina_tekst = pagina.extract_text() or ""
            
            print(
                f"PDF-pagina {nummer}: "
                f"{len(pagina.chars)} teksttekens, "
                f"{len(pagina.images)} afbeeldingen, "
                f"{len(pagina.rects)} rechthoeken, "
                f"{len(pagina.curves)} vectorvormen"
            )

            pagina_teksten.append(pagina_tekst)

            print(f"\n--- PAGINA {nummer} ---")
            print(pagina_tekst[:5000])
            print(f"--- EINDE PAGINA {nummer} ---")

        tekst = "\n".join(pagina_teksten)


    # OCR-test: pagina 2 van de gastariefkaart
    import fitz
    import pytesseract
    from PIL import Image

    with fitz.open(stream=response.content, filetype="pdf") as doc:
        if len(doc) >= 2:
            pagina = doc[1]
            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(2.5, 2.5),
                alpha=False
            )

            afbeelding = Image.frombytes(
                "RGB",
                (pix.width, pix.height),
                pix.samples
            )

            ocr_tekst = pytesseract.image_to_string(
                afbeelding,
                lang="nld+eng",
                config="--psm 3"
            )

            print("\n--- OCR PAGINA 2 ---")
            print(ocr_tekst[:10000])
            print("--- EINDE OCR ---\n")
            
            import re

            formule = re.search(
                r"\(\s*(\d+[,.]\d+)\s*\*\s*TTF-RLP-M\s*\)"
                r"\s*\+\s*(\d+[,.]\d+)",
                ocr_tekst,
                re.IGNORECASE
            )


            if not formule:
                raise ValueError(
                    "Ecofix: prijsformule ontbreekt of is gewijzigd"
                )

            factor = float(formule.group(1).replace(",", "."))
            toeslag = float(formule.group(2).replace(",", "."))
            
            # Vergelijk met de laatst bevestigde Ecofix-formule
            verwachte_factor = 0.1010
            verwachte_toeslag = 0.2200

            if (
                abs(factor - verwachte_factor) > 0.000001
                or abs(toeslag - verwachte_toeslag) > 0.000001
            ):
                raise ValueError(
                    "Ecofix: WIJZIGING IN GASFORMULE!\n"
                    f"Verwacht: {verwachte_factor:.4f} * TTF-RLP-M "
                    f"+ {verwachte_toeslag:.4f}\n"
                    f"Gevonden: {factor:.4f} * TTF-RLP-M "
                    f"+ {toeslag:.4f}\n"
                    "Handmatige controle vereist."
                )


            print("\n--- GECONTROLEERDE GASFORMULE ---")
            print("Index: TTF-RLP-M")
            print(f"Factor: {factor:.4f}")
            print(f"Toeslag: {toeslag:.4f} c€/kWh")
            print("STATUS: PRIJSFORMULE GEVALIDEERD")


    if not tekst.strip():
        raise ValueError("Geen leesbare tekst in de tariefkaart")
        
    print("\n--- UITGELEZEN TARIEFKAART ---")
    print(tekst[:6000])
    print("--- EINDE TARIEFKAART ---\n")


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
