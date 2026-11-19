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
        "verwachte_formule": {
            "index": "TTF-RLP-M",
            "factor": 0.1010,
            "toeslag": 0.2200,
        },
        "vereiste_woorden": [
            "Ecofix Flexy Online",
            "Onze tariefformule voor aardgas",
        ],
    },

    "TotalEnergies myEssential Variabel Gas": {
        "url": "https://totalenergies.be/static/marketing-documents/b2c/tariff-card/latest/MYESSENTIAL_GAS_VL_NL.pdf",
        "status": "verkenning",
    },

    "Luminus BasicFlex Online Gas": {
        "url": "https://energieplatform-vlaanderen.be/tariefkaartarchief?pdf=d1105da725c750ad6570110124ad0eab588d12f27706107efadf84453d467b65",
        "status": "verkenning",
    },
    
    "ENGIE Flow Gas": {
        "url": "https://energieplatform-vlaanderen.be/tariefkaartarchief?pdf=dc12088e63cec5de4e893c6ed2003903804ad794b2b31d08257f3e30ce222da1",
        "status": "verkenning",
    },

    "OCTA+ Boost Flex Gas": {
        "url": "https://energieplatform-vlaanderen.be/tariefkaartarchief?pdf=432590afb3a59d20b4f0050ce67166b7b576aed062da530bcb838a4e49b1e9b0",
        "status": "verkenning",
    },

}

# Algemene herkenning van gasprijsformules

FORMULE_PATROON = re.compile(
    r"\(?\s*(?P<factor>\d+[,.]\d+)\s*[×*x]\s*"
    r"(?P<index>[A-Z][A-Z0-9_./ -]{2,45}?)\s*\)?"
    r"\s*(?P<teken>[+-])\s*(?P<toeslag>\d+[,.]\d+)",
    re.IGNORECASE,
)


def normaliseer_index(index: str) -> str:
    return re.sub(r"\s+", "", index).upper().replace("–", "-")



def herken_formule(tekst: str) -> dict | None:
    def getal(waarde):
        return float(waarde.replace(",", "."))

    # 1. Bestaande herkenning behouden.
    for regel in tekst.splitlines():
        if "tariefformule" not in regel.lower():
            continue
        match = FORMULE_PATROON.search(regel)
        if match:
            break
    else:
        match = FORMULE_PATROON.search(tekst)

    if match:
        toeslag = getal(match.group("toeslag"))
        if match.group("teken") == "-":
            toeslag = -toeslag
        return {
            "index": normaliseer_index(match.group("index")),
            "factor": getal(match.group("factor")),
            "toeslag": toeslag,
        }

    # 2. ENGIE: toeslag + (factor x index)
    engie = re.search(
        r"(?P<toeslag>\d+[,.]\d+)\s*\+\s*\(\s*"
        r"(?P<factor>\d+[,.]\d+)\s*[x×*]\s*"
        r"(?P<index>ZTPDAM\s*\(Heren\))\s*\)",
        tekst,
        re.IGNORECASE,
    )
    if engie:
        return {
            "index": normaliseer_index(engie.group("index")),
            "factor": getal(engie.group("factor")),
            "toeslag": getal(engie.group("toeslag")),
        }

    # 3. OCTA+: index * factor + toeslag
    octa = re.search(
        r"(?P<index>ZTP\s+RLP\s+M)\s*[x×*]\s*"
        r"(?P<factor>\d+[,.]\d+)\s*\+\s*"
        r"(?P<toeslag>\d+[,.]\d+)",
        tekst,
        re.IGNORECASE,
    )
    if octa:
        return {
            "index": normaliseer_index(octa.group("index")),
            "factor": getal(octa.group("factor")),
            "toeslag": getal(octa.group("toeslag")),
        }

    return None



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

    # Verkenningscontracten worden alleen geïnventariseerd: geen prijzen overnemen.
    if gegevens.get("status") == "verkenning":
        gevonden = herken_formule(tekst)
        print(f"PDF: {len(response.content)} bytes; OCR op {ocr_paginas} pagina('s)")
        print("Herkenbare formule:", gevonden if gevonden else "niet gevonden met huidig patroon")
        print("TEKSTFRAGMENT (eerste 2500 tekens):")
        
        if naam in ("ENGIE Flow Gas", "OCTA+ Boost Flex Gas"):
            print("\n--- REGELS MET INDEX OF FORMULE ---")
            for regel in tekst.splitlines():
                if any(
                    woord in regel.upper()
                    for woord in ("TTF", "ZTP", "FORMULE", "INDEX")
                ):
                    print(regel[:300])
            print("--- EINDE FORMULEREGELS ---")

        print(tekst[:2500])
        print("STATUS: VERKENNING — NIET GEVALIDEERD, NIET VOOR BEREKENING")
        return

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
    print(f"\n{'MISLUKT' if fouten else 'GESLAAGD'}: {len(GAS_CONTRACTEN) - fouten}/{len(GAS_CONTRACTEN)} PDF-controles uitgevoerd")
    print("Let op: verkenningscontracten zijn NIET gevalideerd voor prijsberekeningen")
    return 1 if fouten else 0


if __name__ == "__main__":
    sys.exit(main())
