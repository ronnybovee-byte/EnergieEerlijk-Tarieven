
import hashlib
import csv
import io
import os
import tempfile
from decimal import Decimal

from controle_alle_prijzen import (
    CSV_PAD,
    PRODUCTEN,
    VELDEN,
    TARIEFMAAND,
    download_pdf,
    pdf_tekst,
    controleer_contract,
    lees_prijzen,
    bedrag,
)


# Beoordeelde tariefkaarten: uitsluitend standaardafname zonder PV/energiedelen.
# Bedragen omvatten geen reeds apart verwerkte vaste vergoeding of groen/WKK.
GOEDGEKEURDE_PDFS = {
    ("2026-11", "15818"): "2291fbcd3dbed79b159bfc70302bff3680e501e776f7aae5e27e2cb7b4a222b5",
    ("2026-11", "15824"): "854b5c2615b7eb19018352363e0aeaff19e90f8fa31123442ac46992abb2e509",
    ("2026-11", "10667"): "05baf31e5e714d2a44b314313bd11e162bc67776b11a2132e77ea329e39f8688",
    ("2026-11", "12710"): "80a63153926a39f1e5114dbb528604beb87867b3d955a3f4edaf925af4d52858",
    ("2026-11", "17280"): "7e2810ac0f05715cbc52605c65d2ae71819a820649a0ddce2527f208e69630a7",
    ("2026-11", "18399"): "9d315b7ed7d666f45cd60aca723b946e8bf09cb44ea41e243ec26d83d951d2fe",
    ("2026-11", "10940"): "4b8095fad2633bc47bb55065e86c66806eaab72cdbb033c30128662cca8a231f",
    ("2026-11", "16065"): "7f604dc751787ee3bf0f70439bfa9cca338243ff924924ac37eef63a73a1493e",
    ("2026-11", "16083"): "92da547b008edf9ee1a6935bed94bac271af566d15cc4bdd723f239ea4ac7ae8",
    ("2026-11", "17100"): "3089a2a2d544dec9b8a48622cdcd4882b25760e8467343cbfcd21efe78a7b6c3",
    ("2026-11", "13419"): "d182c75cefa9abd0eaddedc0794117ce4f903749393d6180e6c779db2c0f78d7",
    ("2026-11", "18582"): "7b41dd538d299abf3be9808913fe1874c77ba3448a26152443844bf6d9287359",
    ("2026-11", "18405"): "09c4a392b75af832c9aea5774fd61868b35903795ecc707acf4523531ed75b7f",
    ("2026-11", "17211"): "3cfcaacfa5b66541c66f2948bb5c1d6176be46125d475c3acf6360e2128c4862",
}

def overige_kosten(product_id, maand, inhoud):
    verwacht = GOEDGEKEURDE_PDFS.get((maand, product_id))
    if verwacht and hashlib.sha256(inhoud).hexdigest() == verwacht:
        return "0.00", "ja"
    return "", "nee"


def hoofdprogramma():
    with open(CSV_PAD, "rb") as bestand:
        originele_inhoud = bestand.read()

    heeft_bom = originele_inhoud.startswith(b"\xef\xbb\xbf")
    codering = "utf-8-sig" if heeft_bom else "utf-8"

    csv_tekst = originele_inhoud.decode(codering)
    lezer = csv.DictReader(io.StringIO(csv_tekst))
    kolommen = lezer.fieldnames
    producten = list(lezer)

    if not kolommen:
        raise RuntimeError("CSV heeft geen kolomnamen")

    vereiste_kolommen = ("id",) + VELDEN
    if not all(veld in kolommen for veld in vereiste_kolommen):
        raise RuntimeError("Verplichte CSV-kolommen ontbreken")

    gevonden_ids = [rij["id"].strip() for rij in producten]

    if (
        len(producten) != 14
        or len(set(gevonden_ids)) != 14
        or set(gevonden_ids) != set(PRODUCTEN)
    ):
        raise RuntimeError(
            "CSV bevat niet exact de 14 verwachte contracten"
        )

    nieuwe_prijzen = {}
    nieuwe_kosten = {}

    for product in producten:
        product_id = product["id"].strip()
        print(f"Tariefkaart controleren: {product_id}")

        inhoud = download_pdf(product_id)
        paginas = pdf_tekst(inhoud)

        controleer_contract(paginas, product_id)
        prijzen = lees_prijzen(inhoud, paginas, product_id)

        gecontroleerd = {}

        for veld in VELDEN:
            if veld not in prijzen:
                raise ValueError(
                    f"Ontbrekende prijs bij {product_id}: {veld}"
                )

            waarde = bedrag(prijzen[veld])
            if not isinstance(waarde, Decimal):
                waarde = Decimal(str(waarde))

            if not waarde.is_finite() or waarde < 0:
                raise ValueError(
                    f"Ongeldige prijs bij {product_id}: {veld}"
                )

            gecontroleerd[veld] = waarde

        nieuwe_prijzen[product_id] = gecontroleerd
        nieuwe_kosten[product_id] = overige_kosten(product_id, TARIEFMAAND.strftime("%Y-%m"), inhoud)

    tariefmaand = TARIEFMAAND.strftime("%Y-%m")
    wijzigingen = 0

    if "tariefmaand" not in kolommen:
        kolommen = list(kolommen) + ["tariefmaand"]

    for product in producten:
        product_id = product["id"].strip()

        for veld in VELDEN:
            oude_tekst = product[veld]
            oude_waarde = bedrag(oude_tekst)
            nieuwe_waarde = nieuwe_prijzen[product_id][veld]

            if oude_waarde != nieuwe_waarde:
                product[veld] = str(nieuwe_waarde)
                wijzigingen += 1
                print(
                    f"WIJZIGING {product_id} {veld}: "
                    f"{oude_tekst} -> {nieuwe_waarde}"
                )

        if product.get("tariefmaand") != tariefmaand:
            product["tariefmaand"] = tariefmaand

            wijzigingen += 1

        for veld, waarde in zip(
            ("overige_kosten_eur_incl_btw", "overige_kosten_gevalideerd"),
            nieuwe_kosten[product_id],
        ):
            if veld in kolommen and product.get(veld) != waarde:
                product[veld] = waarde
                wijzigingen += 1
                print(f"WIJZIGING {product_id} {veld}: {waarde}")

        print(f"Overige kosten {product_id}: {nieuwe_kosten[product_id][1]}")

    print(f"Tariefmaand: {tariefmaand}")
    print(f"Aantal wijzigingen: {wijzigingen}")

    if wijzigingen == 0:
        print("Geen wijzigingen. CSV blijft ongewijzigd.")
        return

    uitvoer = io.StringIO(newline="")
    schrijver = csv.DictWriter(
        uitvoer,
        fieldnames=kolommen,
        lineterminator="\n",
    )
    schrijver.writeheader()
    schrijver.writerows(producten)

    nieuwe_inhoud = uitvoer.getvalue().encode(codering)

    mapnaam = os.path.dirname(os.path.abspath(CSV_PAD))
    tijdelijk_pad = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=mapnaam,
            delete=False,
        ) as tijdelijk:
            tijdelijk_pad = tijdelijk.name
            tijdelijk.write(nieuwe_inhoud)

        os.replace(tijdelijk_pad, CSV_PAD)

    finally:
        if tijdelijk_pad and os.path.exists(tijdelijk_pad):
            os.unlink(tijdelijk_pad)

    print("CSV succesvol bijgewerkt.")


if __name__ == "__main__":
    hoofdprogramma()
