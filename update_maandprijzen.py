
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


def hoofdprogramma():
    with open(CSV_PAD, "rb") as bestand:
        originele_inhoud = bestand.read()

    heeft_bom = originele_inhoud.startswith(b"\xef\xbb\xbf")
    codering = "utf-8-sig" if heeft_bom else "utf-8"

    csv_tekst = originele_inhoud.decode(codering)

    lezer = csv.DictReader(io.StringIO(csv_tekst))
    kolommen = lezer.fieldnames
    producten = list(lezer)

    gevonden_ids = [rij["id"].strip() for rij in producten]

    if (
        len(producten) != 14
        or len(set(gevonden_ids)) != 14
        or set(gevonden_ids) != set(PRODUCTEN)
    ):
        raise RuntimeError(
            "CSV bevat niet exact de 14 verwachte contracten"
        )

    if not kolommen or not all(
        veld in kolommen for veld in VELDEN
    ):
        raise RuntimeError("CSV-kolommen ontbreken")

    nieuwe_prijzen = {}

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

    wijzigingen = 0

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

    print(
        f"Tariefmaand: {TARIEFMAAND.month:02d}/"
        f"{TARIEFMAAND.year}"
    )
    print(f"Aantal gewijzigde prijzen: {wijzigingen}")

    if wijzigingen == 0:
        print("Geen prijswijzigingen. CSV blijft ongewijzigd.")
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
