
import csv
import io
import re
import urllib.parse
import urllib.request
from decimal import Decimal

import pdfplumber

from lees_tariefkaart import (
    lees_tariefkaart,
    lees_engie_basic_online,
    lees_luminus,
    lees_elegant,
)

CSV_PAD = "tariefkaart_scenarios_v120.csv"
TARIEFDATUM = "1/11/2026 00:00:00"

PRODUCTEN = {
    "18582": ("OCTA+", "Basic Online"),
    "18399": ("OCTA+", "Boost Flex"),
    "15818": ("ENGIE", "Basic Online"),
    "17100": ("Luminus", "BasicFlex Online"),
    "16065": ("Elegant", "Flex"),
    "16083": ("Elegant", "ComfortFlex"),
    "15824": ("ENGIE", "Direct Online"),
    "10667": ("ENGIE", "Flow"),
    "10940": ("OCTA+", "Smart Variabel"),
    "13419": ("Luminus", "MaxxFlex"),
    "12710": ("ENGIE", "Easy"),
    "18405": ("OCTA+", "Eco Boost Flex"),
    "17211": ("Energy Knights", "Essentia Online"),
    "17280": ("Energy Knights", "Essentia Online Green"),
}

VELDEN = (
    "dag_ct",
    "nacht_ct",
    "vast_eur",
    "groen_wkk_ct",
)


def bedrag(waarde):
    return Decimal(str(waarde).strip().replace(",", "."))


def download_pdf(product_id):
    basis = "https://www.vtest.be/Profile/DownloadTariffCard"

    url = basis + "?" + urllib.parse.urlencode({
        "productId": product_id,
        "signUpDate": TARIEFDATUM,
    })

    verzoek = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(verzoek, timeout=45) as antwoord:
        inhoud = antwoord.read(10_000_000)

    if not inhoud.startswith(b"%PDF-"):
        raise ValueError("Download is geen geldige PDF")

    return inhoud


def pdf_tekst(inhoud):
    with pdfplumber.open(io.BytesIO(inhoud)) as document:
        if not document.pages:
            raise ValueError("PDF heeft geen pagina's")

        teksten = [
            pagina.extract_text() or ""
            for pagina in document.pages
        ]

    return teksten


def normale_tekst(tekst):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        tekst.casefold(),
    ).strip()


def controleer_contract(pdf_paginas, product_id):
    leverancier, contract = PRODUCTEN[product_id]

    eerste_pagina = normale_tekst(pdf_paginas[0])

    if normale_tekst(contract) not in eerste_pagina:
        raise ValueError(
            f"Contractnaam niet gevonden in PDF: {contract}"
        )

    if leverancier == "Energy Knights":
        if "energy knights" not in eerste_pagina:
            raise ValueError("Verkeerde leverancier in PDF")

        if "2026 11" not in eerste_pagina:
            raise ValueError("Verkeerde tariefmaand")

    elif leverancier == "OCTA+":
        if "november 2026" not in eerste_pagina:
            raise ValueError("Verkeerde OCTA+-tariefmaand")

    elif leverancier == "Luminus":
        if "november 2026" not in eerste_pagina:
            raise ValueError("Verkeerde Luminus-tariefmaand")

    elif leverancier == "Elegant":
        if "november 2026" not in eerste_pagina:
            raise ValueError("Verkeerde Elegant-tariefmaand")

    elif leverancier == "ENGIE":
        if "november 2026" not in eerste_pagina:
            raise ValueError("Verkeerde ENGIE-tariefmaand")


def lees_energy_bedrag(tekst, label):
    regels = [
        regel.strip()
        for regel in tekst.splitlines()
        if re.search(
            re.escape(label.lower()) + r"\s+\d+,\d{2}(?!\d)",
            regel.lower(),
        )
    ]

    if len(regels) != 1:
        raise ValueError(
            f"{label}: verwacht één prijsregel, "
            f"gevonden {len(regels)}"
        )

    na_label = regels[0].lower().split(
        label.lower(), 1
    )[1]

    gevonden = re.search(
        r"(?<!\d)\d+,\d{2}(?!\d)",
        na_label,
    )

    if not gevonden:
        raise ValueError(f"Geen bedrag gevonden voor {label}")

    return bedrag(gevonden.group())


def lees_energy_knights(paginas, product_id):
    if len(paginas) < 2:
        raise ValueError("Energy Knights PDF is onvolledig")

    p1, p2 = paginas[:2]

    dag = lees_energy_bedrag(
        p1, "Verbruik dag (c€/kWh)"
    )
    nacht = lees_energy_bedrag(
        p1, "Verbruik nacht (c€/kWh)"
    )
    vast = lees_energy_bedrag(
        p1, "Abonnement (€/jaar)"
    )
    groen = lees_energy_bedrag(
        p2, "Bijdrage groene stroom"
    )
    wkk = lees_energy_bedrag(
        p2, "Bijdrage WKK"
    )

    extra = Decimal("0")

    if product_id == "17280":
        extra = lees_energy_bedrag(
            p1, "Groene stroom (c€/kWh)"
        )

    return {
        "dag_ct": dag,
        "nacht_ct": nacht,
        "vast_eur": vast,
        "groen_wkk_ct": groen + wkk + extra,
    }


def lees_prijzen(inhoud, paginas, product_id):
    if product_id in ("17211", "17280"):
        return lees_energy_knights(paginas, product_id)

    # De bestaande uitlezers verwachten een PDF-bestand.
    # Een tijdelijk bestand wordt uitsluitend voor de
    # prijsuitlezing gebruikt en niet in GitHub opgeslagen.
    import os
    import tempfile

    tijdelijk_pad = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
        ) as bestand:
            bestand.write(inhoud)
            tijdelijk_pad = bestand.name

        if product_id in (
            "18582", "18399", "10940", "18405"
        ):
            return lees_tariefkaart(tijdelijk_pad)

        if product_id in (
            "15818", "15824", "10667", "12710"
        ):
            return lees_engie_basic_online(tijdelijk_pad)

        if product_id in ("17100", "13419"):
            return lees_luminus(tijdelijk_pad)

        if product_id in ("16065", "16083"):
            return lees_elegant(tijdelijk_pad)

        raise ValueError(
            f"Geen uitlezer voor product {product_id}"
        )

    finally:
        if tijdelijk_pad and os.path.exists(tijdelijk_pad):
            os.remove(tijdelijk_pad)


def controleer_product(product):
    product_id = product["id"].strip()
    leverancier, contract = PRODUCTEN[product_id]

    print()
    print(f"CONTROLE: {product_id} - {leverancier} - {contract}")

    inhoud = download_pdf(product_id)
    paginas = pdf_tekst(inhoud)

    controleer_contract(paginas, product_id)

    prijzen = lees_prijzen(inhoud, paginas, product_id)

    fouten = []

    for veld in VELDEN:
        if veld not in prijzen:
            raise ValueError(f"Ontbrekende PDF-prijs: {veld}")

        pdf_waarde = bedrag(prijzen[veld])
        csv_waarde = bedrag(product[veld])

        if pdf_waarde == csv_waarde:
            print(
                f"OK {veld}: "
                f"PDF={pdf_waarde} CSV={csv_waarde}"
            )
        else:
            print(
                f"VERSCHIL {veld}: "
                f"PDF={pdf_waarde} CSV={csv_waarde}"
            )
            fouten.append(veld)

    if fouten:
        raise AssertionError(
            "Prijsverschillen: " + ", ".join(fouten)
        )

    print(f"GESLAAGD: {product_id} - 4/4 prijzen")


def hoofdprogramma():
    with open(
        CSV_PAD,
        encoding="utf-8-sig",
        newline="",
    ) as bestand:
        producten = list(csv.DictReader(bestand))

    gevonden_ids = [rij["id"].strip() for rij in producten]

    if len(producten) != 14:
        raise RuntimeError(
            f"Verwacht 14 contracten, gevonden {len(producten)}"
        )

    if (
        len(set(gevonden_ids)) != 14
        or set(gevonden_ids) != set(PRODUCTEN)
    ):
        raise RuntimeError(
            "Product-ID's komen niet overeen met de selectie"
        )

    fouten = []
    geslaagd = 0

    for product in producten:
        product_id = product["id"].strip()

        try:
            controleer_product(product)
            geslaagd += 1

        except Exception as fout:
            print()
            print(f"FOUT bij {product_id}: {fout}")
            fouten.append((product_id, str(fout)))

    print()
    print("=" * 50)
    print(f"RESULTAAT: {geslaagd}/14 contracten geslaagd")

    if fouten:
        for product_id, fout in fouten:
            print(f"FOUT {product_id}: {fout}")

        raise RuntimeError(
            f"{len(fouten)} contract(en) niet geslaagd"
        )

    print("GESLAAGD: alle 56 CSV-prijzen gecontroleerd")


if __name__ == "__main__":
    hoofdprogramma()
