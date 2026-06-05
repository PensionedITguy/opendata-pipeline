"""
parse_or.py - Parser XML souboru Obchodniho rejstriku (justice.cz opendata)
Cil: Z_ORstagg na HPZ4
Slozka: E:/1_OPENDATA/OBCH_REJSTRIK/new/

Spusteni:
    python parse_or.py
    python parse_or.py --folder "E:/1_OPENDATA/OBCH_REJSTRIK/new" --batch 2000

Závislosti:
    pip install pyodbc

ODBC driver: ověř nainstalovanou verzi:
    Get-OdbcDriver | Select-Object Name | Where-Object Name -like "*SQL*"
  a uprav CONN_STRING níže (Driver 17 nebo 18).
"""

import xml.etree.ElementTree as ET
import pyodbc
import re
import argparse
from datetime import datetime
from pathlib import Path
import shutil

# ─── Konfigurace ────────────────────────────────────────────────────────────────

DEFAULT_FOLDER = r"E:\1_OPENDATA\OBCH_REJSTRIK\new"
CONN_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=HPZ4;"
    "DATABASE=Z_ORstagg;"
    "Trusted_Connection=yes;"
)
BATCH_SIZE = 2000          # počet řádků na jeden executemany
LOG_INTERVAL = 10          # výpis progressu každých N souborů

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}", flush=True)

# ─── Pomocné funkce ─────────────────────────────────────────────────────────────

def to_date(s):
    """Převede string 'YYYY-MM-DD' na date nebo None."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None

def safe_str(val, maxlen=490):
    """Bezpecny string - None zustane None, delsi hodnoty se oriznout."""
    if val is None:
        return None
    val = str(val).strip()
    if len(val) > maxlen:
        log(f"  TRIM [{maxlen}]: {val[:80]}...")
        return val[:maxlen]
    return val or None

def adresa_dict(elem):
    """Vrati dict adresnich poli z elementu <adresa>."""
    if elem is None:
        return {}
    return {
        "ADR_STAT":       safe_str(elem.findtext("statNazev")),
        "ADR_OBEC":       safe_str(elem.findtext("obec")),
        "ADR_CAST_OBCE":  safe_str(elem.findtext("castObce")),
        "ADR_ULICE":      safe_str(elem.findtext("ulice")),
        "ADR_CISLO_PO":   safe_str(elem.findtext("cisloPo"), 190),
        "ADR_CISLO_OR":   safe_str(elem.findtext("cisloOr"), 190),
        "ADR_CISLO_TEXT": safe_str(elem.findtext("cisloText"), 190),
        "ADR_PSC":        safe_str(elem.findtext("psc"), 190),
        "ADR_OKRES":      safe_str(elem.findtext("okres")),
    }

def parse_pravni_forma(filename):
    """Extrahuje kód právní formy z názvu souboru, např. 'sro' z 'sro-full-brno-2026.xml'."""
    m = re.match(r"^([a-z0-9_]+)-(?:full|actual)-", Path(filename).name.lower())
    return m.group(1) if m else None

# ─── Parsování jednoho subjektu ──────────────────────────────────────────────────

def parse_subjekt(elem, pravni_forma_kod):
    """
    Zpracuje element <Subjekt> a vrátí tuple:
        (subjekt_row, fo_list, po_list, vazba_list, adresa_hist_list)
    """
    ico = elem.findtext("ico", "").strip()
    if not ico:
        return None

    nazev       = safe_str(elem.findtext("nazev"))
    zapis_datum = to_date(elem.findtext("zapisDatum"))
    vymaz_datum = to_date(elem.findtext("vymazDatum"))

    # Sbírat všechny SIDLO záznamy → aktuální = nejmladší zapisDatum
    sidla = []
    spis_zn = None
    soud_kod = None
    pf_kod = None
    pf_naz = None

    for udaj in elem.findall("udaje/Udaj"):
        typ_elem = udaj.find("udajTyp")
        if typ_elem is None:
            continue
        kod = typ_elem.findtext("kod")

        if kod == "SIDLO":
            sidla.append({
                "zapisDatum": to_date(udaj.findtext("zapisDatum")),
                "adresa":     adresa_dict(udaj.find("adresa")),
            })

        elif kod == "SPIS_ZN":
            spis_zn = udaj.findtext("hodnotaText")
            spis_elem = udaj.find("spisZn")
            if spis_elem is not None:
                soud_elem = spis_elem.find("soud")
                if soud_elem is not None:
                    soud_kod = soud_elem.findtext("kod")

        elif kod == "PRAVNI_FORMA":
            pf_elem = udaj.find("pravniForma")
            if pf_elem is not None:
                pf_kod = pf_elem.findtext("kod")
                pf_naz = pf_elem.findtext("nazev")

    # Aktuální sídlo = nejmladší zapisDatum
    akt_sidlo = {}
    akt_sidlo_datum = None
    if sidla:
        sidla.sort(key=lambda x: x["zapisDatum"] or datetime.min.date())
        akt = sidla[-1]
        akt_sidlo = akt["adresa"]
        akt_sidlo_datum = akt["zapisDatum"]

    subjekt_row = (
        ico, nazev,
        pf_kod or pravni_forma_kod, pf_naz,
        zapis_datum, vymaz_datum,
        spis_zn, soud_kod,
        akt_sidlo.get("ADR_STAT"),
        akt_sidlo.get("ADR_OBEC"),
        akt_sidlo.get("ADR_CAST_OBCE"),
        akt_sidlo.get("ADR_ULICE"),
        akt_sidlo.get("ADR_CISLO_PO"),
        akt_sidlo.get("ADR_CISLO_OR"),
        akt_sidlo.get("ADR_CISLO_TEXT"),
        akt_sidlo.get("ADR_PSC"),
        akt_sidlo.get("ADR_OKRES"),
        akt_sidlo_datum,
    )

    # Historické adresy sídla (všechny kromě aktuální)
    adresa_hist_list = []
    for s in sidla[:-1]:
        a = s["adresa"]
        adresa_hist_list.append((
            "SUBJEKT_SIDLO", ico, None,
            a.get("ADR_STAT"), a.get("ADR_OBEC"), a.get("ADR_CAST_OBCE"),
            a.get("ADR_ULICE"), a.get("ADR_CISLO_PO"), a.get("ADR_CISLO_OR"),
            a.get("ADR_CISLO_TEXT"), a.get("ADR_PSC"), a.get("ADR_OKRES"),
            s["zapisDatum"], None,
        ))

    # ── Angažmá ─────────────────────────────────────────────────────────────────
    fo_dict  = {}   # (prijmeni, jmeno, narozDatum) → fo data
    po_dict  = {}   # ico → po data
    vazba_list = []

    def zpracuj_clen_udaj(udaj, subjekt_ico):
        """Zpracuje jeden <Udaj> s T=F nebo T=P a přidá do fo_dict/po_dict/vazba_list."""
        ho = udaj.find("hodnotaUdaje")
        if ho is None:
            return
        t = ho.findtext("T")
        typ_elem = udaj.find("udajTyp")
        udaj_typ_kod = typ_elem.findtext("kod") if typ_elem is not None else None

        zapis_d  = to_date(udaj.findtext("zapisDatum"))
        vymaz_d  = to_date(udaj.findtext("vymazDatum"))
        funkce   = safe_str(udaj.findtext("funkce"), 490)
        f_od     = to_date(udaj.findtext("funkceOd"))
        f_do     = to_date(udaj.findtext("funkceDo"))
        cl_od    = to_date(udaj.findtext("clenstviOd"))
        cl_do    = to_date(udaj.findtext("clenstviDo"))
        adr      = adresa_dict(udaj.find("adresa"))

        if t == "F":
            osoba = udaj.find("osoba")
            if osoba is None:
                return
            jmeno    = osoba.findtext("jmeno", "").strip()
            prijmeni = osoba.findtext("prijmeni", "").strip()
            narozen  = to_date(osoba.findtext("narozDatum"))
            if not (jmeno and prijmeni and narozen):
                return

            fo_key = (prijmeni.upper(), jmeno.upper(), narozen)
            if fo_key not in fo_dict:
                fo_dict[fo_key] = {
                    "JMENO":       jmeno,
                    "PRIJMENI":    prijmeni,
                    "TITUL_PRED":  safe_str(osoba.findtext("titulPred"), 190),
                    "TITUL_ZA":    safe_str(osoba.findtext("titulZa"), 190),
                    "NAROZENI_DATUM": narozen,
                    "STAT_KOD":    (osoba.find("stat") if osoba.find("stat") is not None else ET.Element("x")).findtext("kod"),
                    # adresa – zatím uložíme, přepíšeme pokud nalezneme novější
                    "ADR_DATUM":   zapis_d,
                    "ADR":         adr,
                }
            else:
                # aktualizovat adresu pokud tento zápisový akt je novější
                existing = fo_dict[fo_key]
                if (existing["ADR_DATUM"] or datetime.min.date()) < (zapis_d or datetime.min.date()):
                    existing["ADR_DATUM"] = zapis_d
                    existing["ADR"]       = adr

            # vazba
            vazba_list.append((
                subjekt_ico,
                fo_key,   # nahradíme FO_ID po insertu
                None,     # PO_ICO
                None,     # ZASTOUPENI_FO_ID
                funkce, f_od, f_do, cl_od, cl_do,
                zapis_d, vymaz_d,
                udaj_typ_kod, pravni_forma_kod,
                adr.get("ADR_STAT"), adr.get("ADR_OBEC"), adr.get("ADR_CAST_OBCE"),
                adr.get("ADR_ULICE"), adr.get("ADR_CISLO_PO"), adr.get("ADR_CISLO_OR"),
                adr.get("ADR_CISLO_TEXT"), adr.get("ADR_PSC"), adr.get("ADR_OKRES"),
            ))

        elif t == "P":
            osoba = udaj.find("osoba")
            if osoba is None:
                return
            po_ico_val = osoba.findtext("ico", "").strip()
            po_nazev   = safe_str(osoba.findtext("nazev"))
            if not po_ico_val:
                return

            if po_ico_val not in po_dict:
                po_dict[po_ico_val] = {
                    "NAZEV":    po_nazev,
                    "ADR_DATUM": zapis_d,
                    "ADR":       adr,
                }
            else:
                existing = po_dict[po_ico_val]
                if (existing["ADR_DATUM"] or datetime.min.date()) < (zapis_d or datetime.min.date()):
                    existing["ADR_DATUM"] = zapis_d
                    existing["ADR"]       = adr

            # Zjistit zástupce FO (STATUTARNI_ORGAN_ZASTOUPENI v podudaje)
            zastoupeni_fo_key = None
            for pod in udaj.findall("podudaje/Udaj"):
                pod_ho = pod.find("hodnotaUdaje")
                pod_typ = pod.find("udajTyp")
                if (pod_ho is not None and pod_ho.findtext("T") == "F"
                        and pod_typ is not None
                        and pod_typ.findtext("kod") == "STATUTARNI_ORGAN_ZASTOUPENI"):
                    zast_osoba = pod.find("osoba")
                    if zast_osoba is not None:
                        zj = zast_osoba.findtext("jmeno", "").strip()
                        zp = zast_osoba.findtext("prijmeni", "").strip()
                        zn = to_date(zast_osoba.findtext("narozDatum"))
                        if zj and zp and zn:
                            zastoupeni_fo_key = (zp.upper(), zj.upper(), zn)
                            if zastoupeni_fo_key not in fo_dict:
                                zast_adr = adresa_dict(pod.find("adresa"))
                                fo_dict[zastoupeni_fo_key] = {
                                    "JMENO":       zj,
                                    "PRIJMENI":    zp,
                                    "TITUL_PRED":  safe_str(zast_osoba.findtext("titulPred"), 190),
                                    "TITUL_ZA":    safe_str(zast_osoba.findtext("titulZa"), 190),
                                    "NAROZENI_DATUM": zn,
                                    "STAT_KOD":    (zast_osoba.find("stat") if zast_osoba.find("stat") is not None else ET.Element("x")).findtext("kod"),
                                    "ADR_DATUM":   to_date(pod.findtext("zapisDatum")),
                                    "ADR":         zast_adr,
                                }
                    break

            vazba_list.append((
                subjekt_ico,
                None,         # FO_ID
                po_ico_val,   # PO_ICO
                zastoupeni_fo_key,  # nahradíme FO_ID po insertu
                funkce, f_od, f_do, cl_od, cl_do,
                zapis_d, vymaz_d,
                udaj_typ_kod, pravni_forma_kod,
                adr.get("ADR_STAT"), adr.get("ADR_OBEC"), adr.get("ADR_CAST_OBCE"),
                adr.get("ADR_ULICE"), adr.get("ADR_CISLO_PO"), adr.get("ADR_CISLO_OR"),
                adr.get("ADR_CISLO_TEXT"), adr.get("ADR_PSC"), adr.get("ADR_OKRES"),
            ))

    # Procházíme udaje na top úrovni
    for udaj in elem.findall("udaje/Udaj"):
        zpracuj_clen_udaj(udaj, ico)
        # Zanořené podudaje (např. členové uvnitř STATUTARNI_ORGAN sekce)
        for pod in udaj.findall("podudaje/Udaj"):
            zpracuj_clen_udaj(pod, ico)

    return subjekt_row, fo_dict, po_dict, vazba_list, adresa_hist_list


# ─── SQL helper ──────────────────────────────────────────────────────────────────

def bulk_insert(cursor, table, columns, rows):
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    cols = ", ".join(f"[{c}]" for c in columns)
    sql = f"INSERT INTO [dbo].[{table}] ({cols}) VALUES ({placeholders})"
    cursor.executemany(sql, rows)


# ─── Hlavní zpracování ────────────────────────────────────────────────────────────

def process_folder(folder, conn_string, batch_size):
    xml_files = sorted(Path(folder).glob("*.xml"))
    if not xml_files:
        log.error(f"Žádné XML soubory v: {folder}")
        return

    log(f"Nalezeno {len(xml_files)} XML souborů v {folder}")
    processed_dir = Path(folder) / ".." / "processed"
    processed_dir = processed_dir.resolve()
    processed_dir.mkdir(exist_ok=True)
    log(f"Zpracovane soubory budou presunute do: {processed_dir}")

    conn = pyodbc.connect(conn_string, autocommit=False)
    cursor = conn.cursor()
    # fast_executemany=True inferuje typ z první hodnoty v dávce - při kratší první hodnotě
    # ořízne delší hodnoty v téže dávce. Pro staging s různorodými daty vypnuto.
    cursor.fast_executemany = False

    total_subjekty  = 0
    total_fo        = 0
    total_po        = 0
    total_vazby     = 0
    total_adr_hist  = 0

    # Globální FO registr přes celé zpracování (deduplikace across files)
    # Předplnit z DB pro případ restartu - načteme všechny existující FO
    fo_registry = {}   # (prijmeni_upper, jmeno_upper, narozen) → FO_ID
    log("Nacitam existujici FO z DB...")
    cursor.execute("SELECT [FO_ID],[PRIJMENI],[JMENO],[NAROZENI_DATUM] FROM [dbo].[or_osoba_fo]")
    for row in cursor.fetchall():
        fo_id, prijmeni, jmeno, narozen = row
        if prijmeni and jmeno and narozen:
            fo_registry[(prijmeni.upper(), jmeno.upper(), narozen)] = fo_id
    log(f"Nacteno {len(fo_registry):,} FO z DB")

    # Načíst seznam ICO která už jsou v DB - pro přeskočení hotových souborů
    cursor.execute("SELECT [ICO] FROM [dbo].[or_subjekt]")
    existing_ico = {row[0] for row in cursor.fetchall()}
    log(f"V DB je {len(existing_ico):,} existujicich subjektu")

    for file_idx, xml_path in enumerate(xml_files, 1):
        if file_idx % LOG_INTERVAL == 0 or file_idx == 1:
            log(f"[{file_idx}/{len(xml_files)}] {xml_path.name}")

        pravni_forma_kod = parse_pravni_forma(xml_path.name)

        # Rychlá kontrola - přeskočit soubor pokud první ICO v něm už je v DB
        first_ico = None
        try:
            for _, elem in ET.iterparse(str(xml_path), events=("end",)):
                if elem.tag == "ico":
                    first_ico = elem.text.strip() if elem.text else None
                    elem.clear()
                    break
                elem.clear()
        except Exception:
            pass
        if first_ico and first_ico in existing_ico:
            log(f"  SKIP - jiz zpracovano (ICO {first_ico})")
            continue

        # Dávkové buffery
        subjekt_rows    = []
        fo_new_rows     = []   # (key, row_tuple)
        po_rows         = {}   # ico → row
        vazba_rows      = []
        adresa_hist_rows = []

        # Lokální fo_dict pro tento soubor – po parsování promítneme do fo_registry
        local_fo = {}  # key → fo data dict

        try:
            context = ET.iterparse(str(xml_path), events=("end",))
            for event, elem in context:
                if elem.tag != "Subjekt":
                    continue

                result = parse_subjekt(elem, pravni_forma_kod)
                elem.clear()
                if result is None:
                    continue

                s_row, fo_dict, po_dict, vazba_list, adr_hist = result

                subjekt_rows.append(s_row)
                adresa_hist_rows.extend(adr_hist)

                for fo_key, fo_data in fo_dict.items():
                    if fo_key in local_fo:
                        # aktualizovat adresu pokud novější
                        existing = local_fo[fo_key]
                        if (existing["ADR_DATUM"] or datetime.min.date()) < (fo_data["ADR_DATUM"] or datetime.min.date()):
                            existing["ADR_DATUM"] = fo_data["ADR_DATUM"]
                            existing["ADR"]       = fo_data["ADR"]
                    else:
                        local_fo[fo_key] = fo_data

                for po_ico, po_data in po_dict.items():
                    if po_ico not in po_rows:
                        po_rows[po_ico] = po_data
                    else:
                        existing = po_rows[po_ico]
                        if (existing["ADR_DATUM"] or datetime.min.date()) < (po_data["ADR_DATUM"] or datetime.min.date()):
                            po_rows[po_ico] = po_data

                vazba_rows.extend(vazba_list)

                total_subjekty += 1

                # Flush per batch
                if len(subjekt_rows) >= batch_size:
                    _flush(cursor, subjekt_rows, local_fo, po_rows, vazba_rows,
                           adresa_hist_rows, fo_registry)
                    total_fo     += len(local_fo)
                    total_po     += len(po_rows)
                    total_vazby  += len(vazba_rows)
                    total_adr_hist += len(adresa_hist_rows)
                    subjekt_rows = []
                    local_fo     = {}
                    po_rows      = {}
                    vazba_rows   = []
                    adresa_hist_rows = []

            # Flush zbytku souboru
            if subjekt_rows:
                _flush(cursor, subjekt_rows, local_fo, po_rows, vazba_rows,
                       adresa_hist_rows, fo_registry)
                total_fo     += len(local_fo)
                total_po     += len(po_rows)
                total_vazby  += len(vazba_rows)
                total_adr_hist += len(adresa_hist_rows)

            conn.commit()
            # Přesunout zpracovaný soubor do processed/
            shutil.move(str(xml_path), processed_dir / xml_path.name)
            log(f"  -> presunuto do processed/")

        except Exception as e:
            conn.rollback()
            log(f"CHYBA při zpracování {xml_path.name}: {e}")
            raise

    cursor.close()
    conn.close()

    log("=" * 60)
    log("Hotovo.")
    log(f"  Subjektů:        {total_subjekty:>10,}")
    log(f"  Fyzických osob:  {total_fo:>10,}")
    log(f"  Práv. osob:      {total_po:>10,}")
    log(f"  Vazeb:           {total_vazby:>10,}")
    log(f"  Hist. adres:     {total_adr_hist:>10,}")


def _flush(cursor, subjekt_rows, local_fo, po_rows, vazba_rows,
           adresa_hist_rows, fo_registry):
    """Zapíše dávku do DB a aktualizuje fo_registry."""

    # ── or_subjekt (INSERT OR IGNORE duplicate ICO) ──────────────────────────
    if subjekt_rows:
        sql = """
            IF NOT EXISTS (SELECT 1 FROM [dbo].[or_subjekt] WHERE [ICO] = ?)
            INSERT INTO [dbo].[or_subjekt]
              ([ICO],[NAZEV],[PRAVNI_FORMA_KOD],[PRAVNI_FORMA_NAZ],
               [ZAPIS_DATUM],[VYMAZ_DATUM],[SPIS_ZN],[SOUD_KOD],
               [ADR_STAT],[ADR_OBEC],[ADR_CAST_OBCE],[ADR_ULICE],
               [ADR_CISLO_PO],[ADR_CISLO_OR],[ADR_CISLO_TEXT],
               [ADR_PSC],[ADR_OKRES],[ADR_ZAPIS_DATUM])
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        for row in subjekt_rows:
            cursor.execute(sql, (row[0],) + row)

    # ── or_osoba_fo (MERGE přes prijmeni+jmeno+narozen) ──────────────────────
    new_fo_keys = [k for k in local_fo if k not in fo_registry]
    if new_fo_keys:
        fo_insert = []
        for k in new_fo_keys:
            d = local_fo[k]
            a = d["ADR"]
            fo_insert.append((
                d["JMENO"], d["PRIJMENI"], d["TITUL_PRED"], d["TITUL_ZA"],
                d["NAROZENI_DATUM"], d["STAT_KOD"],
                a.get("ADR_STAT"), a.get("ADR_OBEC"), a.get("ADR_CAST_OBCE"),
                a.get("ADR_ULICE"), a.get("ADR_CISLO_PO"), a.get("ADR_CISLO_OR"),
                a.get("ADR_CISLO_TEXT"), a.get("ADR_PSC"), a.get("ADR_OKRES"),
                d["ADR_DATUM"],
            ))
        sql_fo = """
            IF NOT EXISTS (
                SELECT 1 FROM [dbo].[or_osoba_fo]
                WHERE [PRIJMENI]=? AND [JMENO]=? AND [NAROZENI_DATUM]=?
            )
            INSERT INTO [dbo].[or_osoba_fo]
              ([JMENO],[PRIJMENI],[TITUL_PRED],[TITUL_ZA],[NAROZENI_DATUM],[STAT_KOD],
               [ADR_STAT],[ADR_OBEC],[ADR_CAST_OBCE],[ADR_ULICE],
               [ADR_CISLO_PO],[ADR_CISLO_OR],[ADR_CISLO_TEXT],
               [ADR_PSC],[ADR_OKRES],[ADR_ZAPIS_DATUM])
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
        # IF NOT EXISTS potřebuje prijmeni, jmeno, narozen jako první 3 parametry
        fo_insert_safe = [
            (r[1], r[0], r[4]) + r
            for r in fo_insert
        ]
        for row in fo_insert_safe:
            cursor.execute(sql_fo, row)

        # Načíst zpět vygenerované FO_ID
        for k in new_fo_keys:
            d = local_fo[k]
            cursor.execute(
                "SELECT [FO_ID] FROM [dbo].[or_osoba_fo] "
                "WHERE [PRIJMENI]=? AND [JMENO]=? AND [NAROZENI_DATUM]=?",
                (d["PRIJMENI"], d["JMENO"], d["NAROZENI_DATUM"])
            )
            row = cursor.fetchone()
            if row:
                fo_registry[k] = row[0]

    # ── or_osoba_po ───────────────────────────────────────────────────────────
    if po_rows:
        for po_ico, d in po_rows.items():
            a = d["ADR"]
            cursor.execute("""
                IF NOT EXISTS (SELECT 1 FROM [dbo].[or_osoba_po] WHERE [PO_ICO]=?)
                INSERT INTO [dbo].[or_osoba_po]
                  ([PO_ICO],[NAZEV],[ADR_STAT],[ADR_OBEC],[ADR_CAST_OBCE],[ADR_ULICE],
                   [ADR_CISLO_PO],[ADR_CISLO_OR],[ADR_CISLO_TEXT],
                   [ADR_PSC],[ADR_OKRES],[ADR_ZAPIS_DATUM])
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                po_ico, po_ico, d["NAZEV"],
                a.get("ADR_STAT"), a.get("ADR_OBEC"), a.get("ADR_CAST_OBCE"),
                a.get("ADR_ULICE"), a.get("ADR_CISLO_PO"), a.get("ADR_CISLO_OR"),
                a.get("ADR_CISLO_TEXT"), a.get("ADR_PSC"), a.get("ADR_OKRES"),
                d["ADR_DATUM"],
            ))

    # ── or_vazba ──────────────────────────────────────────────────────────────
    if vazba_rows:
        vazba_insert = []
        for v in vazba_rows:
            # v[1] = fo_key nebo None, v[3] = zastoupeni_fo_key nebo None
            fo_id       = fo_registry.get(v[1]) if v[1] else None
            zast_fo_id  = fo_registry.get(v[3]) if v[3] else None
            vazba_insert.append((
                v[0],            # SUBJEKT_ICO
                fo_id,           # FO_ID
                v[2],            # PO_ICO
                zast_fo_id,      # ZASTOUPENI_FO_ID
                v[4], v[5], v[6], v[7], v[8],   # FUNKCE, FUNKCE_OD/DO, CLENSTVI_OD/DO
                v[9], v[10],     # ZAPIS_DATUM, VYMAZ_DATUM
                v[11], v[12],    # UDAJ_TYP_KOD, PRAVNI_FORMA_KOD
                v[13], v[14], v[15], v[16], v[17], v[18], v[19], v[20], v[21],  # ADR
            ))
        bulk_insert(cursor, "or_vazba", [
            "SUBJEKT_ICO","FO_ID","PO_ICO","ZASTOUPENI_FO_ID",
            "FUNKCE","FUNKCE_OD","FUNKCE_DO","CLENSTVI_OD","CLENSTVI_DO",
            "ZAPIS_DATUM","VYMAZ_DATUM","UDAJ_TYP_KOD","PRAVNI_FORMA_KOD",
            "ADR_STAT","ADR_OBEC","ADR_CAST_OBCE","ADR_ULICE",
            "ADR_CISLO_PO","ADR_CISLO_OR","ADR_CISLO_TEXT","ADR_PSC","ADR_OKRES",
        ], vazba_insert)

    # ── or_adresa_hist ────────────────────────────────────────────────────────
    if adresa_hist_rows:
        # Přeložit REF_FO_ID (zatím None pro subjektní adresy)
        bulk_insert(cursor, "or_adresa_hist", [
            "TYP","REF_ICO","REF_FO_ID",
            "ADR_STAT","ADR_OBEC","ADR_CAST_OBCE","ADR_ULICE",
            "ADR_CISLO_PO","ADR_CISLO_OR","ADR_CISLO_TEXT","ADR_PSC","ADR_OKRES",
            "ZAPIS_DATUM","VYMAZ_DATUM",
        ], adresa_hist_rows)


# ─── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parser OR XML → Z_ORstagg")
    parser.add_argument("--folder", default=DEFAULT_FOLDER,
                        help=f"Složka s XML soubory (default: {DEFAULT_FOLDER})")
    parser.add_argument("--batch",  type=int, default=BATCH_SIZE,
                        help=f"Velikost dávky (default: {BATCH_SIZE})")
    parser.add_argument("--server", default=None,
                        help="Override SQL Server (default z CONN_STRING)")
    args = parser.parse_args()

    conn_str = CONN_STRING
    if args.server:
        conn_str = re.sub(r"SERVER=[^;]+", f"SERVER={args.server}", conn_str)

    t0 = datetime.now()
    process_folder(args.folder, conn_str, args.batch)
    log(f"Celkový čas: {datetime.now() - t0}")
