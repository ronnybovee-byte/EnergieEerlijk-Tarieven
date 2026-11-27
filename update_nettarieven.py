import argparse
import json
import math
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
from tempfile import TemporaryDirectory
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
from tempfile import TemporaryDirectory
import re

from openpyxl import load_workbook


BESTAND = Path(__file__).resolve().parent / (
    "nettarieven_fluvius_antwerpen.json"
)


def controle(voorwaarde, melding):
    if not voorwaarde:
        raise ValueError(melding)


def tekst(waarde):
    return " ".join(str(waarde or "").lower().split())


def controle_cel(ws, cel, verwacht):
    controle(
        tekst(ws[cel].value) == tekst(verwacht),
        f"{ws.title}: afwijkende inhoud in {cel}"
    )


def controle_werkblad(ws, jaar, energie):
    titel = tekst(ws["A1"].value)

    controle(
        titel == tekst(
            f"Fluvius Antwerpen - {energie} - "
            f"Tarieflijst periodieke distributienettarieven "
            f"{jaar} - Afname"
        ),
        "Onjuiste netbeheerder, energie, jaar of tariefsoort"
    )

    inhoud = " ".join(
        tekst(cel.value)
        for rij in ws.iter_rows()
        for cel in rij
        if isinstance(cel.value, str)
    )

    controle(
        f"01/01/{jaar} t.e.m. 31/12/{jaar}" in inhoud,
        "Onjuiste geldigheidsperiode"
    )

    controle(
        "tarieven zonder btw" in inhoud,
        "BTW-status niet bevestigd"
    )


def lees_tarief(ws, cel, labelcel, label, eenheidcel, eenheid):
    controle_cel(ws, labelcel, label)
    controle_cel(ws, eenheidcel, eenheid)

    waarde = ws[cel].value

    controle(
        isinstance(waarde, (int, float))
        and not isinstance(waarde, bool)
        and math.isfinite(waarde)
        and waarde >= 0,
        f"Ongeldig tarief in {ws.title}!{cel}"
    )

    return waarde


def lees_elektriciteit(pad, jaar):
    wb = load_workbook(pad, data_only=True)
    ws = wb["FA ELEK Afname"]

    controle_werkblad(ws, jaar, "ELEKTRICITEIT")
    controle_cel(ws, "O5", "analoge meter")
    controle_cel(
        ws, "B18",
        "Afnameklanten op laagspanningsnet met analoge "
        "(terugdraaiende) meter"
    )

    gegevens = {
        "meter": "analoog"
    }

    velden = [
        ("vaste_term_eur_jaar", "O19", "B19",
         "Vaste term", "D19", "EUR/jaar"),

        ("databeheer_eur_jaar", "O27", "B27",
         "Laagspanningnet", "D27", "EUR/jaar"),

        ("netgebruik_eur_kwh", "O20", "B20",
         "kWh-tarief", "D20", "EUR/kWh"),

        ("openbare_dienst_eur_kwh", "O30", "B30",
         "kWh-tarief normaal", "D30", "EUR/kWh"),

        ("toeslagen_eur_kwh", "O33", "B33",
         "Tarieven voor de toeslagen *3", "D33", "EUR/kWh")
    ]

    for naam, *specificatie in velden:
        gegevens[naam] = lees_tarief(ws, *specificatie)

    wb.close()
    return gegevens


def lees_gas(pad, jaar):
    wb = load_workbook(pad, data_only=True)
    ws = wb["FA GAS Afname"]

    controle_werkblad(ws, jaar, "AARDGAS")
    controle_cel(ws, "E6", "T2")
    controle_cel(ws, "E8", "5 001 - 150 000")

    controle(
        "D22:G22" in {
            str(bereik) for bereik in ws.merged_cells.ranges
        },
        "Afwijkende structuur gasdatabeheer"
    )

    gegevens = {
        "categorie": "T2"
    }

    velden = [
        ("vaste_term_eur_jaar", "E13", "B13",
         "Vaste term", "C13", "EUR/jaar"),

        ("databeheer_eur_jaar", "D22", "B22",
         "Jaaropname (o.a. digitale gasmeter G4 en G6 "
         "voor huishoudelijk en kleine ondernemingen)",
         "C22", "EUR/jaar"),

        ("netgebruik_eur_kwh", "E14", "B14",
         "Proportionele term", "C14", "EUR/kWh"),

        ("openbare_dienst_eur_kwh", "E24", "A24",
         "II. Het tarief openbaredienstverplichtingen",
         "C24", "EUR/kWh"),

        ("pensioenlasten_eur_kwh", "E27", "B27",
         "Lasten van niet-gekapitaliseerde pensioenen",
         "C27", "EUR/kWh"),

        ("retributies_eur_kwh", "E28", "B28",
         "Retributies en heffingen van publieke overheden "
         "of openbare domeinbeheerders",
         "C28", "EUR/kWh")
    ]

    for naam, *specificatie in velden:
        gegevens[naam] = lees_tarief(ws, *specificatie)

    wb.close()
    return gegevens

BRON_URL = (
    "https://www.vlaamsenutsregulator.be/"
    "elektriciteit-en-aardgas/nettarieven/"
    "hoeveel-bedragen-de-distributienettarieven"
)


def officiele_url(url):
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "www.vlaamsenutsregulator.be",
            "assets.vlaamsenutsregulator.be",
            "vlaamsenutsregulator.be"
        }
    )


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def download(url):
    controle(officiele_url(url), "Niet-officiele bron")

    request = Request(
        url,
        headers={"User-Agent": "EerlijkeEnergie/1.0"}
    )

    with urlopen(request, timeout=60) as response:
        controle(
            officiele_url(response.geturl()),
            "Niet-officiele downloadbestemming"
        )

        inhoud = response.read(10_000_001)

    controle(
        len(inhoud) <= 10_000_000,
        "Bestand onverwacht groot"
    )

    return inhoud


def zoek_officiele_bestanden(gewenst_jaar=None):
    parser = LinkParser()
    parser.feed(download(BRON_URL).decode("utf-8"))

    gevonden = {}

    for href in parser.links:
        url = urljoin(BRON_URL, href)

        if not officiele_url(url):
            continue

        naam = unquote(
            urlparse(url).path.rsplit("/", 1)[-1]
        ).lower()

        match = re.fullmatch(
            r"distributienettarieven[\s_-]+"
            r"(elektriciteit|aardgas)[\s_-]+"
            r"(20\d{2})\.xlsx",
            naam
        )

        if not match:
            continue

        energie, jaar = match.groups()
        jaar = int(jaar)

        gevonden.setdefault(jaar, {})
        gevonden[jaar].setdefault(energie, set()).add(url)

    controle(
        bool(gevonden),
        "Geen officiele Excelbestanden gevonden"
    )

    jaar = (
        gewenst_jaar
        if gewenst_jaar is not None
        else max(gevonden)
    )

    bestanden = gevonden.get(jaar, {})

    for energie in ("elektriciteit", "aardgas"):
        controle(
            len(bestanden.get(energie, set())) == 1,
            f"Ontbrekende of dubbele bron: {energie} {jaar}"
        )

    return (
        jaar,
        next(iter(bestanden["elektriciteit"])),
        next(iter(bestanden["aardgas"]))
    )


def lees_online(jaar=None):
    jaar, elek_url, gas_url = (
        zoek_officiele_bestanden(jaar)
    )

    print(f"Officieel tariefjaar: {jaar}")
    print(f"Elektriciteit: {elek_url}")
    print(f"Aardgas: {gas_url}")

    with TemporaryDirectory() as mapnaam:
        elek = Path(mapnaam) / "elektriciteit.xlsx"
        gas = Path(mapnaam) / "aardgas.xlsx"

        elek.write_bytes(download(elek_url))
        gas.write_bytes(download(gas_url))

        return jaar, {
            "geldig_vanaf": f"{jaar}-01-01",
            "geldig_tot": f"{jaar}-12-31",
            "elektriciteit": lees_elektriciteit(elek, jaar),
            "gas": lees_gas(gas, jaar)
        }
BRON_URL = (
    "https://www.vlaamsenutsregulator.be/"
    "elektriciteit-en-aardgas/nettarieven/"
    "hoeveel-bedragen-de-distributienettarieven"
)


def officiele_url(url):
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {
            "www.vlaamsenutsregulator.be",
            "assets.vlaamsenutsregulator.be",
            "vlaamsenutsregulator.be"
        }
    )


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def download(url):
    controle(officiele_url(url), "Niet-officiele bron")

    request = Request(
        url,
        headers={"User-Agent": "EerlijkeEnergie/1.0"}
    )

    with urlopen(request, timeout=60) as response:
        controle(
            officiele_url(response.geturl()),
            "Niet-officiele downloadbestemming"
        )

        inhoud = response.read(10_000_001)

    controle(
        len(inhoud) <= 10_000_000,
        "Bestand onverwacht groot"
    )

    return inhoud


def zoek_officiele_bestanden(gewenst_jaar=None):
    parser = LinkParser()
    parser.feed(download(BRON_URL).decode("utf-8"))

    gevonden = {}

    for href in parser.links:
        url = urljoin(BRON_URL, href)

        if not officiele_url(url):
            continue

        naam = unquote(
            urlparse(url).path.rsplit("/", 1)[-1]
        ).lower()

        match = re.fullmatch(
            r"distributienettarieven[\s_-]+"
            r"(elektriciteit|aardgas)[\s_-]+"
            r"(20\d{2})\.xlsx",
            naam
        )

        if not match:
            continue

        energie, jaar = match.groups()
        jaar = int(jaar)

        gevonden.setdefault(jaar, {})
        gevonden[jaar].setdefault(energie, set()).add(url)

    controle(
        bool(gevonden),
        "Geen officiele Excelbestanden gevonden"
    )

    jaar = (
        gewenst_jaar
        if gewenst_jaar is not None
        else max(gevonden)
    )

    bestanden = gevonden.get(jaar, {})

    for energie in ("elektriciteit", "aardgas"):
        controle(
            len(bestanden.get(energie, set())) == 1,
            f"Ontbrekende of dubbele bron: {energie} {jaar}"
        )

    return (
        jaar,
        next(iter(bestanden["elektriciteit"])),
        next(iter(bestanden["aardgas"]))
    )


def lees_online(jaar=None):
    jaar, elek_url, gas_url = (
        zoek_officiele_bestanden(jaar)
    )

    print(f"Officieel tariefjaar: {jaar}")
    print(f"Elektriciteit: {elek_url}")
    print(f"Aardgas: {gas_url}")

    with TemporaryDirectory() as mapnaam:
        elek = Path(mapnaam) / "elektriciteit.xlsx"
        gas = Path(mapnaam) / "aardgas.xlsx"

        elek.write_bytes(download(elek_url))
        gas.write_bytes(download(gas_url))

        return jaar, {
            "geldig_vanaf": f"{jaar}-01-01",
            "geldig_tot": f"{jaar}-12-31",
            "elektriciteit": lees_elektriciteit(elek, jaar),
            "gas": lees_gas(gas, jaar)
        }
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jaar", type=int)
    parser.add_argument("--elektriciteit")
    parser.add_argument("--gas")
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--publiceren", action="store_true")
    args = parser.parse_args()

    if args.online:
        controle(
            not args.elektriciteit and not args.gas,
            "Online en lokale bronnen niet combineren"
        )

        jaar, nieuw = lees_online(args.jaar)

    else:
        controle(
            args.jaar and args.elektriciteit and args.gas,
            "Jaar en beide Excelbestanden verplicht"
        )

        jaar = args.jaar

        nieuw = {
            "geldig_vanaf": f"{jaar}-01-01",
            "geldig_tot": f"{jaar}-12-31",
            "elektriciteit": lees_elektriciteit(
                args.elektriciteit, jaar
            ),
            "gas": lees_gas(args.gas, jaar)
        }

    data = json.loads(BESTAND.read_text(encoding="utf-8"))

    controle(
        data.get("schema_version") == 1
        and data.get("netbeheerder") == "Fluvius Antwerpen"
        and data.get("inclusief_btw") is False,
        "Ongeldige centrale nettariefbron"
    )

    bestaand = data["tarieven"].get(str(jaar))

    print(json.dumps(nieuw, indent=2, ensure_ascii=False))

    if bestaand == nieuw:
        print("OK: alle tarieven komen exact overeen.")
        return

    if bestaand is not None:
        raise ValueError(
            "Bestaande jaartarieven wijken af. "
            "Handmatige controle vereist."
        )

    if not args.publiceren:
        print("Controle geslaagd. Geen publicatie uitgevoerd.")
        return

    data["tarieven"][str(jaar)] = nieuw

    tijdelijk = BESTAND.with_suffix(".tmp")

    tijdelijk.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    tijdelijk.replace(BESTAND)

    print(f"Nettarieven {jaar} toegevoegd.")


if __name__ == "__main__":
    main()
