#!/usr/bin/env python3
"""Controleer officiële gastariefkaarten via tekstextractie en OCR.

Contracten worden centraal geconfigureerd. Onzekere of gewijzigde formules
worden gemeld en nooit automatisch overgenomen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import re
import sys

import fitz
import pdfplumber
import pytesseract
import requests
from PIL import Image

GAS_CONTRACTEN = {
    "Ecofix Flexy Online": {
        "url": "https://portal.ecofixgp.be/docs/prices/current/GAS_Ecofix_Flexy_Online_NL.pdf",
        "verwachte_formule": {"index": "TTF-RLP-M", "factor": 0.1010, "toeslag": 0.2200},
        "vereiste_woorden": ["Ecofix Flexy Online", "Onze tariefformule voor aardgas"],
    },
}

# Herkent de veelvoorkomende vorm '(factor * index) + toeslag'.
# Een leverancier met een afwijkende formule vereist een extra parser.
FORMULE_PATROON = re.compile(
    r"\(\s*(?P<factor>\d+[,.]\d+)\s*[×*x]\s*"
    r"(?P<index>[A-Z][A-Z0-9 _./-]{2,45}?)\s*\)\s*"
    r"(?P<teken>[+-])\s*(?P<toeslag>\d+[,.]\d+)",
    re.IGNORECASE,
)


def normaliseer_index(index: str) -> str:
    return re.sub(r"\s+", "", index).upper().replace("–", "-")


def herken_formule(tekst: str) -> dict | None:
    # Zoek bij voorkeur vlak na de expliciete tariefformule-aanduiding.
    for regel in tekst.splitlines():
        if "tariefformule" not in regel.lower():
            continue
        match = FORMULE_PATROON.search(regel)
        if match:
            break
    else:
        match = FORMULE_PATROON.search(tekst)
    if not match:
        return None
    toeslag = float(match.group("toeslag").replace(",", "."))
    if match.group("teken") == "-":
        toeslag = -toeslag
    return {
        "index": normaliseer_index(match.group("index")),
        "factor": float(match.group("factor").replace(",", ".")),
        "toeslag": toeslag,
    }


def lees_pdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Lees alle pagina's; OCR alleen waar de tekstlaag erg beperkt is."""
    pagina_teksten = []
    ocr_paginas = 0
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf, fitz.open(
        stream=pdf_bytes, filetype="pdf"
    ) as doc:
        if len(pdf.pages) != len(doc):
            raise ValueError("PDF-pagina's komen niet overeen")
        if not doc:
            raise ValueError("Lege PDF")
        if len(doc) > 20:
            raise ValueError("Onverwacht lange tariefkaart; handmatige controle vereist")
        for nummer, (pagina, fitz_pagina) in enumerate(zip(pdf.pages, doc), start=1):
            tekst = pagina.extract_text() or ""
            if len(tekst.strip()) < 120:
                pix = fitz_pagina.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
                afbeelding = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                ocr = pytesseract.image_to_string(afbeelding, lang="nld+eng", config="--psm 3")
                if ocr.strip():
                    tekst += "\n" + ocr
                ocr_paginas += 1
            pagina_teksten.append(tekst)
            print(f"Pagina {nummer}: {len(tekst.strip())} tekens na extractie/OCR")
    return "\n".join(pagina_teksten), ocr_paginas


def controleer_tariefkaart(naam: str, gegevens: dict) -> None:
    print(f"\nControle: {naam}")
    response = requests.get(
        gegevens["url"], timeout=45, headers={"User-Agent": "EerlijkeEnergie/1.0"}
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise ValueError("Download is geen PDF")
    if len(response.content) > 15_000_000:
        raise ValueError("PDF groter dan 15 MB")

    tekst, ocr_paginas = lees_pdf(response.content)
    if not tekst.strip():
        raise ValueError("Geen leesbare tekst")
    ontbrekend = [w for w in gegevens.get("vereiste_woorden", []) if w.casefold() not in tekst.casefold()]
    if ontbrekend:
        raise ValueError(f"Contractidentificatie ontbreekt: {ontbrekend}")

    gevonden = herken_formule(tekst)
    if gevonden is None:
        raise ValueError("Geen herkenbare formule; handmatige controle vereist")
    print(f"Gevonden index: {gevonden['index']}")
    print(f"Gevonden factor: {gevonden['factor']:.4f}")
    print(f"Gevonden toeslag: {gevonden['toeslag']:.4f} c€/kWh")

    verwacht = gegevens["verwachte_formule"]
    if (gevonden["index"] != normaliseer_index(verwacht["index"])
        or abs(gevonden["factor"] - verwacht["factor"]) > 0.000001
        or abs(gevonden["toeslag"] - verwacht["toeslag"]) > 0.000001):
        raise ValueError(f"FORMULE GEWIJZIGD: verwacht {verwacht}; gevonden {gevonden}. Handmatige controle vereist")
    print(f"PDF: {len(response.content)} bytes; OCR op {ocr_paginas} pagina('s)")
    print("STATUS: PRIJSFORMULE GEVALIDEERD")
    print("Let op: actuele maandprijs en vaste vergoeding nog niet gevalideerd")


def main() -> int:
    print("Eerlijke Energie - centrale controle gastariefkaarten")
    print("Controle uitgevoerd:", datetime.now(timezone.utc).isoformat())
    fouten = 0
    for naam, gegevens in GAS_CONTRACTEN.items():
        try:
            controleer_tariefkaart(naam, gegevens)
        except Exception as fout:
            fouten += 1
            print(f"FOUT bij {naam}: {fout}")
    print(f"\n{'MISLUKT' if fouten else 'GESLAAGD'}: {len(GAS_CONTRACTEN) - fouten}/{len(GAS_CONTRACTEN)} contracten gevalideerd")
    return 1 if fouten else 0


if __name__ == "__main__":
    sys.exit(main())
