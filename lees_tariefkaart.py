
import csv
import re
import sys
from decimal import Decimal

import pdfplumber


def bedrag(tekst):
    return Decimal(tekst.replace(",", "."))


def zoek_prijs(tekst, patroon, omschrijving):
    resultaat = re.search(
        patroon, tekst, flags=re.IGNORECASE
    )
    if not resultaat:
        raise ValueError(
            f"Niet gevonden in PDF: {omschrijving}"
        )
    return bedrag(resultaat.group(1))


def lees_tariefkaart(pdf_pad):
    with pdfplumber.open(pdf_pad) as pdf:
        if len(pdf.pages) < 2:
            raise ValueError("Tariefkaart heeft te weinig pagina's")

        pagina1 = pdf.pages[0].extract_text() or ""
        pagina2 = pdf.pages[1].extract_text() or ""

    if not re.search(
        r"TARIEFFICHE\s+NOVEMBER\s+2026",
        pagina1, re.IGNORECASE
    ):
        raise ValueError("Dit is niet de novembertariefkaart")

    dag = zoek_prijs(
        pagina1,
        r"Tweevoudige meter\s*-\s*Piekuren\s+([\d,.]+)",
        "dagtarief"
    )
    nacht = zoek_prijs(
        pagina1,
        r"Tweevoudige meter\s*-\s*Daluren\s+([\d,.]+)",
        "nachttarief"
    )
    vast = zoek_prijs(
        pagina1,
        r"Vaste vergoeding\s*\(€/jaar\)\s+([\d,.]+)",
        "vaste vergoeding"
    )

    groen = zoek_prijs(
        pagina2,
        r"Kosten groene stroom\s+([\d,.]+)",
        "groene stroom"
    )
    wkk = zoek_prijs(
        pagina2,
        r"Kosten WKK\s+([\d,.]+)",
        "WKK"
    )

    return {
        "dag_ct": dag,
        "nacht_ct": nacht,
        "vast_eur": vast,
        "groen_wkk_ct": groen + wkk,
    }


def controleer(pdf_pad, csv_pad):
    metingen = lees_tariefkaart(pdf_pad)

    with open(csv_pad, encoding="utf-8-sig", newline="") as bestand:
        producten = list(csv.DictReader(bestand))

    product = next(
        (rij for rij in producten if rij["id"].strip() == "18582"),
        None
    )
    if product is None:
        raise ValueError("Product 18582 ontbreekt in CSV")

    fouten = []

    for veld, waarde in metingen.items():
        verwacht = bedrag(product[veld].strip())
        status = "OK" if waarde == verwacht else "VERSCHIL"
        print(f"{veld}: PDF={waarde} CSV={verwacht} {status}")

        if waarde != verwacht:
            fouten.append(veld)

    if fouten:
        raise ValueError(
            "Prijsverschillen gevonden: " + ", ".join(fouten)
        )

    print("GESLAAGD: alle vier de prijzen komen overeen")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(
            "Gebruik: python lees_tariefkaart.py "
            "<tariefkaart.pdf> <selectie.csv>"
        )

    controleer(sys.argv[1], sys.argv[2])

def lees_engie_basic_online(pdf_pad):
    """Lees de geschatte jaarprijzen uit de ENGIE-tariefkaart."""
    with pdfplumber.open(pdf_pad) as pdf:
        tekst = pdf.pages[0].extract_text() or ""

    if not any(naam in tekst for naam in ("Basic Online", "Direct Online", "Flow", "Easy")) or "November 2026" not in tekst:
        raise ValueError("Onverwachte ENGIE-tariefkaart")

    # ENGIE toont eerst maandprijzen en daarna jaarprijzen.
    # Neem uitsluitend de tweede rij 'Afname'.
    regels = tekst.splitlines()
    afname_regels = [
        regel for regel in regels
        if re.search(r"\bAfname\b", regel, re.IGNORECASE)
    ]

    if len(afname_regels) != 2:
        raise ValueError(
            f"Verwacht 2 afnameregels, gevonden: {len(afname_regels)}"
        )

    jaarregel = afname_regels[1]

    waarden = re.findall(r"\d+,\d+", jaarregel)

    if len(waarden) != 5:
        raise ValueError(
            f"Onverwachte ENGIE-prijsregel: {jaarregel}"
        )

    vast = re.search(
        r"(\d+,\d+)\s*€/jaar", tekst
    )
    if not vast:
        raise ValueError("ENGIE vaste vergoeding niet gevonden")

    return {
        "dag_ct": bedrag(waarden[1]),
        "nacht_ct": bedrag(waarden[2]),
        "vast_eur": bedrag(vast.group(1)),
        "groen_wkk_ct": bedrag(waarden[4]),
    }

def lees_luminus(pdf_pad):
    """Lees de jaarschatting uit een Luminus-tariefkaart."""
    with pdfplumber.open(pdf_pad) as pdf:
        tekst = pdf.pages[0].extract_text() or ""

    kop = "\n".join(tekst.splitlines()[:8])

    if not any(
        naam in kop
        for naam in ("BasicFlex Online", "MaxxFlex")
    ):
        raise ValueError("Onverwacht Luminus-contract")

    if not re.search(r"november\s+2026", kop, re.IGNORECASE):
        raise ValueError("Onverwachte Luminus-tariefmaand")

    # Neem de jaarschatting, niet de actuele energieprijs.
    patroon = (
        r"Jaarschatting energieprijs\s*\(c€/kWh\)\s*2?"
        r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)"
    )

    gevonden = re.search(patroon, tekst, re.IGNORECASE)

    if not gevonden:
        raise ValueError("Luminus-jaarschatting niet gevonden")

    vast = re.search(
        r"Vaste vergoeding\s*\(€/jaar\)\s+([\d,]+)",
        tekst,
        re.IGNORECASE
    )

    if not vast:
        raise ValueError("Luminus vaste vergoeding niet gevonden")

    return {
        "dag_ct": bedrag(gevonden.group(2)),
        "nacht_ct": bedrag(gevonden.group(3)),
        "vast_eur": bedrag(vast.group(1)),
        "groen_wkk_ct": Decimal("0"),
    }

