"""
import_or_v2.py - RAW import Obchodního rejstříku do Z_ORstagg
==============================================================
Tabulky:
  src_OR_Entity  - 1 řádek = 1 právní entita (ICO)
  src_OR_Udaje   - 1 řádek = 1 zápis/výmaz (osoby, sídla, orgány, kapitál, ...)

Spuštění:
  python import_or_v2.py
  python import_or_v2.py --folder "E:/1_OPENDATA/OBCH_REJSTRIK/new" --batch 500

Závislosti: pip install pyodbc
"""

import xml.etree.ElementTree as ET
import pyodbc
import re
import argparse
import shutil
from pathlib import Path
from datetime import datetime

# ── Konfigurace ───────────────────────────────────────────────────────────────

DEFAULT_FOLDER = r"E:\1_OPENDATA\OBCH_REJSTRIK\new"
PROCESSED_DIR  = r"E:\1_OPENDATA\OBCH_REJSTRIK\processed"

CONN_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=HPZ4;"
    "DATABASE=Z_ORstagg;"
    "Trusted_Connection=yes;"
)
BATCH_SIZE = 500   # subjektů na jeden commit

# ── Pomocné funkce ────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):
    try:
        print(f"{ts()}  {msg}", flush=True)
    except UnicodeEncodeError:
        print(f"{ts()}  {msg.encode('ascii','replace').decode('ascii')}", flush=True)

def strip_ns(tag):
    return re.sub(r'^\{[^}]+\}', '', tag)

def find_child(elem, tag):
    for child in elem:
        if strip_ns(child.tag) == tag:
            return child
    return None

def find_all(elem, tag):
    return [c for c in elem if strip_ns(c.tag) == tag]

def get_text(elem, *path):
    """Prochází cestu tagů a vrátí text posledního elementu."""
    cur = elem
    for tag in path:
        cur = find_child(cur, tag)
        if cur is None:
            return None
    return cur.text.strip() if cur is not None and cur.text else None

def safe(s, maxlen=490):
    if s is None:
        return None
    s = str(s).strip()
    return s[:maxlen] if s else None

def to_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

def to_dec(s):
    if not s:
        return None
    try:
        return float(str(s).strip().replace(',', '.'))
    except ValueError:
        return None

def to_int(s):
    if not s:
        return None
    try:
        v = int(str(s).strip())
        return v if -2147483648 <= v <= 2147483647 else None
    except (ValueError, TypeError):
        return None

def parse_adresa(elem):
    if elem is None:
        return {}
    return {
        'obec':      safe(get_text(elem, 'obec')),
        'cast':      safe(get_text(elem, 'castObce')),
        'ulice':     safe(get_text(elem, 'ulice')),
        'cislo_po':  safe(get_text(elem, 'cisloPo')),
        'cislo_or':  safe(get_text(elem, 'cisloOr')),
        'psc':       safe(get_text(elem, 'psc'), 5),
        'okres':     safe(get_text(elem, 'okres')),
        'stat':      safe(get_text(elem, 'statNazev')),
    }

def pravni_forma_z_nazvu(filename):
    """sro-full-plzen-2026.xml → 'sro'"""
    m = re.match(r'^([a-z0-9_]+)-(?:full|actual)-', Path(filename).name.lower())
    return m.group(1) if m else None

# ── Parsování jednoho Subjektu ────────────────────────────────────────────────

def parse_subjekt(elem, pf_kod, soubor, entity_rows, udaj_rows):
    """
    Zpracuje <Subjekt>, plní entity_rows a udaj_rows.
    Vrátí ICO nebo None.
    """
    ico      = safe(get_text(elem, 'ico'), 8)
    nazev    = safe(get_text(elem, 'nazev'), 490)
    zapis_d  = to_date(get_text(elem, 'zapisDatum'))
    vymaz_d  = to_date(get_text(elem, 'vymazDatum'))

    if not ico:
        return None

    entity_rows.append((ico, pf_kod, nazev, zapis_d, vymaz_d, soubor))

    udaje_el = find_child(elem, 'udaje')
    if udaje_el is not None:
        for udaj in find_all(udaje_el, 'Udaj'):
            zpracuj_udaj(udaj, ico, udaj_rows, parent_typ=None)

    return ico


def zpracuj_udaj(udaj, ico, udaj_rows, parent_typ):
    """Zpracuje jeden <Udaj> nebo <podudaj>, rekurzivně."""

    ut_el         = find_child(udaj, 'udajTyp')
    udaj_typ_kod  = safe(get_text(ut_el, 'kod')) if ut_el is not None else None
    udaj_typ_naz  = safe(get_text(ut_el, 'nazev')) if ut_el is not None else None
    hlavicka      = safe(get_text(udaj, 'hlavicka'))
    hodnota_text  = safe(get_text(udaj, 'hodnotaText'), 2000)
    zapis_d       = to_date(get_text(udaj, 'zapisDatum'))
    vymaz_d       = to_date(get_text(udaj, 'vymazDatum'))
    funkce        = safe(get_text(udaj, 'funkce'))
    funkce_od     = to_date(get_text(udaj, 'funkceOd'))
    funkce_do     = to_date(get_text(udaj, 'funkceDo'))
    clenstvi_od   = to_date(get_text(udaj, 'clenstviOd'))
    clenstvi_do   = to_date(get_text(udaj, 'clenstviDo'))

    ho_el  = find_child(udaj, 'hodnotaUdaje')
    osoba_typ = None
    if ho_el is not None:
        t = get_text(ho_el, 'T')
        if t in ('F', 'P', 'S'):
            osoba_typ = t
        elif t is not None:
            osoba_typ = safe(t, 1)

    # -- Fyzická osoba --
    fo_jmeno = fo_prijmeni = fo_titul_p = fo_titul_z = None
    fo_narozeni = fo_stat_kod = fo_stat_naz = None

    # -- Právnická osoba --
    po_ico = po_nazev = po_euid = None

    # -- Adresa --
    adr = {}

    # -- Finanční --
    fin_hod = fin_hod_typ = fin_spl = fin_spl_typ = None
    fin_souh = fin_souh_typ = None

    # -- Akcie --
    akcie_podoba = akcie_typ = akcie_pocet = druh_podilu = None

    # -- Spisová značka --
    spzn_soud_kod = spzn_soud_naz = spzn_oddil = spzn_vlozka = None

    osoba_el = find_child(udaj, 'osoba')
    if osoba_el is not None and osoba_typ == 'F':
        fo_jmeno    = safe(get_text(osoba_el, 'jmeno'))
        fo_prijmeni = safe(get_text(osoba_el, 'prijmeni'))
        fo_titul_p  = safe(get_text(osoba_el, 'titulPred'))
        fo_titul_z  = safe(get_text(osoba_el, 'titulZa'))
        fo_narozeni = to_date(get_text(osoba_el, 'narozDatum'))
        stat_el     = find_child(osoba_el, 'stat')
        if stat_el is not None:
            fo_stat_kod = safe(get_text(stat_el, 'kod'))
            fo_stat_naz = safe(get_text(stat_el, 'nazev'))
        adr = parse_adresa(find_child(udaj, 'adresa'))

    elif osoba_el is not None and osoba_typ == 'P':
        po_ico   = safe(get_text(osoba_el, 'ico'), 8)
        po_nazev = safe(get_text(osoba_el, 'nazev'), 490)
        po_euid  = safe(get_text(osoba_el, 'euid'))
        adr = parse_adresa(find_child(udaj, 'adresa'))

    elif osoba_el is not None:
        # typ S nebo neznámý - zachytit co je
        fo_jmeno    = safe(get_text(osoba_el, 'jmeno'))
        fo_prijmeni = safe(get_text(osoba_el, 'prijmeni'))
        fo_narozeni = to_date(get_text(osoba_el, 'narozDatum'))
        po_ico      = safe(get_text(osoba_el, 'ico'), 8)
        po_nazev    = safe(get_text(osoba_el, 'nazev'), 490)
        adr = parse_adresa(find_child(udaj, 'adresa'))

    # Adresa bez osoby (SIDLO apod.)
    if not adr:
        adr = parse_adresa(find_child(udaj, 'adresa'))

    # Finanční hodnoty z hodnotaUdaje
    if ho_el is not None:
        vklad_el   = find_child(ho_el, 'vklad')
        splaceni_el = find_child(ho_el, 'splaceni')
        souhrn_el  = find_child(ho_el, 'souhrn')
        hodnota_el = find_child(ho_el, 'hodnota')

        # vklad nebo hodnota
        target_fin = vklad_el if vklad_el is not None else hodnota_el
        if target_fin is not None:
            fin_hod     = to_dec(get_text(target_fin, 'textValue'))
            fin_hod_typ = safe(get_text(target_fin, 'typ'))

        if splaceni_el is not None:
            fin_spl     = to_dec(get_text(splaceni_el, 'textValue'))
            fin_spl_typ = safe(get_text(splaceni_el, 'typ'))

        if souhrn_el is not None:
            fin_souh     = to_dec(get_text(souhrn_el, 'textValue'))
            fin_souh_typ = safe(get_text(souhrn_el, 'typ'))

        akcie_podoba = safe(get_text(ho_el, 'podoba'))
        akcie_typ    = safe(get_text(ho_el, 'typ'))
        akcie_pocet  = to_int(get_text(ho_el, 'pocet'))
        druh_podilu  = safe(get_text(ho_el, 'druhPodilu'))

    # Spisová značka
    spzn_el = find_child(udaj, 'spisZn')
    if spzn_el is not None:
        soud_el       = find_child(spzn_el, 'soud')
        spzn_soud_kod = safe(get_text(soud_el, 'kod')) if soud_el is not None else None
        spzn_soud_naz = safe(get_text(soud_el, 'nazev')) if soud_el is not None else None
        spzn_oddil    = safe(get_text(spzn_el, 'oddil'))
        spzn_vlozka   = safe(get_text(spzn_el, 'vlozka'))

    udaj_rows.append((
        ico,
        udaj_typ_kod, udaj_typ_naz, parent_typ,
        hlavicka, hodnota_text, osoba_typ,
        zapis_d, vymaz_d,
        fo_jmeno, fo_prijmeni, fo_titul_p, fo_titul_z,
        fo_narozeni, fo_stat_kod, fo_stat_naz,
        po_ico, po_nazev, po_euid,
        funkce, funkce_od, funkce_do, clenstvi_od, clenstvi_do,
        adr.get('obec'), adr.get('cast'), adr.get('ulice'),
        adr.get('cislo_po'), adr.get('cislo_or'),
        adr.get('psc'), adr.get('okres'), adr.get('stat'),
        fin_hod, fin_hod_typ, fin_spl, fin_spl_typ,
        fin_souh, fin_souh_typ,
        akcie_podoba, akcie_typ, akcie_pocet, druh_podilu,
        spzn_soud_kod, spzn_soud_naz, spzn_oddil, spzn_vlozka,
    ))

    # Rekurze do podudajů
    pod_el = find_child(udaj, 'podudaje')
    if pod_el is not None:
        for pod in find_all(pod_el, 'Udaj'):
            zpracuj_udaj(pod, ico, udaj_rows, parent_typ=udaj_typ_kod)


# ── SQL ───────────────────────────────────────────────────────────────────────

SQL_ENTITY = """
IF NOT EXISTS (SELECT 1 FROM dbo.src_OR_Entity WHERE ICO = ?)
INSERT INTO dbo.src_OR_Entity
  (ICO, PravniFormaKod, Nazev, ZapisDatum, VymazDatum, SoubornNazev)
VALUES (?,?,?,?,?,?)
"""

SQL_UDAJ = """
INSERT INTO dbo.src_OR_Udaje
  (ICO,
   UdajTypKod, UdajTypNazev, ParentUdajTypKod,
   Hlavicka, HodnotaText, OsobaTyp,
   ZapisDatum, VymazDatum,
   FO_Jmeno, FO_Prijmeni, FO_TitulPred, FO_TitulZa,
   FO_Narozeni, FO_StatKod, FO_StatNazev,
   PO_ICO, PO_Nazev, PO_EUID,
   Funkce, FunkceOd, FunkceDo, ClenstviOd, ClenstviDo,
   AdrObec, AdrCastObce, AdrUlice, AdrCisloPo, AdrCisloOr,
   AdrPSC, AdrOkres, AdrStatNazev,
   FinHodnota, FinHodnotaTyp, FinSplaceni, FinSplaceniTyp,
   FinSouhrn, FinSouhrnTyp,
   AkciePodoba, AkcieTyp, AkciePocet, DruhPodilu,
   SpZnSoudKod, SpZnSoudNazev, SpZnOddil, SpZnVlozka,
   EntityID)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
  (SELECT EntityID FROM dbo.src_OR_Entity WHERE ICO = ?))
"""


# ── Hlavní logika ─────────────────────────────────────────────────────────────

def flush(cursor, conn, entity_rows, udaj_rows):
    for row in entity_rows:
        cursor.execute(SQL_ENTITY, (row[0],) + row)

    if udaj_rows:
        ico_list = list({r[0] for r in udaj_rows})
        pl = ','.join(['?'] * len(ico_list))
        cursor.execute(
            f"SELECT ICO, EntityID FROM dbo.src_OR_Entity WHERE ICO IN ({pl})",
            ico_list
        )
        id_map = {r[0]: r[1] for r in cursor.fetchall()}

        insert = []
        for row in udaj_rows:
            eid = id_map.get(row[0])
            if eid:
                insert.append(row + (row[0],))
        if insert:
            cursor.executemany(SQL_UDAJ, insert)

    conn.commit()


def process_folder(folder, processed, conn_string, batch_size):
    folder_path = Path(folder)
    proc_path   = Path(processed)
    proc_path.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(folder_path.glob("*.xml"))
    if not xml_files:
        log(f"Žádné XML soubory v {folder}")
        return

    log(f"Nalezeno {len(xml_files)} souborů")

    conn   = pyodbc.connect(conn_string, autocommit=False)
    cursor = conn.cursor()
    cursor.fast_executemany = False

    total = {'soubory': 0, 'entity': 0, 'udaje': 0}

    for idx, xml_path in enumerate(xml_files, 1):
        log(f"[{idx}/{len(xml_files)}] {xml_path.name}")
        pf_kod  = pravni_forma_z_nazvu(xml_path.name)
        soubor  = xml_path.name

        entity_rows = []
        udaj_rows   = []
        subj_count  = 0

        try:
            context = ET.iterparse(str(xml_path), events=('end',))
            for event, elem in context:
                if strip_ns(elem.tag) != 'Subjekt':
                    continue

                parse_subjekt(elem, pf_kod, soubor, entity_rows, udaj_rows)
                subj_count += 1
                elem.clear()

                if subj_count % batch_size == 0:
                    flush(cursor, conn, entity_rows, udaj_rows)
                    total['entity'] += len(entity_rows)
                    total['udaje']  += len(udaj_rows)
                    entity_rows = []
                    udaj_rows   = []
                    log(f"  ... {subj_count} subjektů zpracováno")

            # zbytek
            if entity_rows:
                flush(cursor, conn, entity_rows, udaj_rows)
                total['entity'] += len(entity_rows)
                total['udaje']  += len(udaj_rows)
            total['soubory'] += 1
            log(f"  -> {subj_count} subjektů, commit OK")
            shutil.move(str(xml_path), proc_path / xml_path.name)

        except Exception as e:
            conn.rollback()
            log(f"CHYBA {xml_path.name}: {e}")
            import traceback
            traceback.print_exc()

    cursor.close()
    conn.close()

    log("=" * 55)
    log(f"Hotovo.")
    log(f"  Souborů: {total['soubory']:>10,}")
    log(f"  Entit:   {total['entity']:>10,}")
    log(f"  Údajů:   {total['udaje']:>10,}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAW import OR → Z_ORstagg")
    parser.add_argument("--folder",    default=DEFAULT_FOLDER)
    parser.add_argument("--processed", default=PROCESSED_DIR)
    parser.add_argument("--batch",     type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    t0 = datetime.now()
    log("=== import_or_v2.py ===")
    process_folder(args.folder, args.processed, CONN_STRING, args.batch)
    log(f"Celkový čas: {datetime.now() - t0}")
