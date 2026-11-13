
import csv
import io
import os
import tempfile

from controle_alle_prijzen import (
    CSV_PAD,
    PRODUCTEN,
    VELDEN,
    download_pdf,
    pdf_tekst,
    controleer_contract,
    lees_prijzen,
    bedrag,
)


def hoofdprogramma():
    with open(
        CSV_PAD,
        encoding="utf-8-sig",
        newline="",
    ) as bestand:
        lezer = csv.DictReader(bestand)
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

    nieuwe_prijzen = {}

    for product in producten:
        product_id = product["id"].strip()

        inhoud = download_pdf(product_id)
        paginas = pdf_tekst(inhoud)

        controleer_contract(paginas, product_id)
        prijzen = lees_prijzen(inhoud, paginas, product_id)

        for veld in VELDEN:
            if veld not in prijzen:
                raise ValueError(
                    f"Ontbrekende prijs bij {product_id}: {veld}"
                )

            bedrag(prijzen[veld])

        nieuwe_prijzen[product_id] = prijzen

    for product in producten:
        product_id = product["id"].strip()
        prijzen = nieuwe_prijzen[product_id]

        for veld in VELDEN:
            product[veld] = str(bedrag(prijzen[veld]))

    uitvoer = io.StringIO(newline="")
    schrijver = csv.DictWriter(
        uitvoer,
        fieldnames=kolommen,
    )
    schrijver.writeheader()
    schrijver.writerows(producten)

    mapnaam = os.path.dirname(os.path.abspath(CSV_PAD))

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        dir=mapnaam,
        delete=False,
    ) as tijdelijk:
        tijdelijk.write(uitvoer.getvalue())
        tijdelijk_pad = tijdelijk.name

    os.replace(tijdelijk_pad, CSV_PAD)


if __name__ == "__main__":
    hoofdprogramma()
