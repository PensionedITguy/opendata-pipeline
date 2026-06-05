"""
import_or.py - RAW import Obchodniho rejstriku do Z_ORstagg
============================================================
Tabulky:
  raw_or_entity  - 1 radek = 1 pravni entita (ICO, nazev, datumy)
  raw_or_organy  - 1 radek = 1 angazma osoby (FO nebo PO)
  raw_or_podily  - 1 radek = 1 zaznam o podilu/vkladu

Spusteni:
  python import_or.py
  python import_or.py --folder "E:/1_OPENDATA/OBCH_REJSTRIK/new" --batch 2000

Zavislosti: pip install pyodbc
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
CONN_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=HPZ4;"
    "DATABASE=Z_ORstagg;"
    "Trusted_Connection=yes;"
)
BATCH_SIZE   = 2000
LOG_INTERVAL = 1     # vypis progressu kazdeho souboru

# Typy udaju ktere jdou do raw_or_organy
ORGAN_TYPY = {
    'STATUTARNI_ORGAN_CLEN', 'KONTROLNI_KOMISE_CLEN',
    'DOZORCI_RADA_CLEN', 'SPRAVNI_RADA_CLEN',
    'LIKVIDATOR', 'INSOLVENCNI_SPRAVCE',
    'PROKURISTA', 'VEDOUCI_ORGANIZACNI_SLOZKY',
    'SPOLECNIK', 'CLEN_DRUZSTVA',
    'ZAKLADATEL', 'CLEN',
}

# Typy udaju ktere jdou do raw_or_podily
PODIL_TYPY = {
    'OBCHODNI_PODIL', 'VKLAD', 'AKCIE',
    'CLENSKY_VKLAD', 'ZAKLADNI_KAPITAL',
    'VKLAD_SPOLECNIKA',
}

# ── Pomocne funkce ────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):
    try:
        print(f"{ts()}  {msg}", flush=True)
    except UnicodeEncodeError:
        safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
        print(f"{ts()}  {safe_msg}", flush=True)

def strip_ns(tag):
    return re.sub(r'^\{[^}]+\}', '', tag)

def txt(elem, path):
    """Najde prvni element na dane ceste a vrati jeho text."""
    parts = path.split('/')
    cur = elem
    for part in parts:
        found = None
        for child in cur:
            if strip_ns(child.tag) == part:
                found = child
                break
        if found is None:
            return None
        cur = found
    return safe_str(cur.text)

def safe_str(s, maxlen=490):
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

def to_int(s):
    if not s:
        return None
    try:
        v = int(str(s).strip())
        # SQL Server int max: 2,147,483,647
        if v > 2147483647 or v < -2147483648:
            return None  # prilis velke cislo - ignorovat
        return v
    except (ValueError, TypeError):
        return None

def parse_adresa(elem):
    """Vrati dict adresních polí z elementu <adresa>."""
    if elem is None:
        return {}
    return {
        'stat':      safe_str(txt(elem, 'statNazev')),
        'obec':      safe_str(txt(elem, 'obec')),
        'cast':      safe_str(txt(elem, 'castObce')),
        'ulice':     safe_str(txt(elem, 'ulice')),
        'cislo_po':  safe_str(txt(elem, 'cisloPo')),
        'cislo_or':  safe_str(txt(elem, 'cisloOr')),
        'cislo_txt': safe_str(txt(elem, 'cisloText')),
        'psc':       safe_str(txt(elem, 'psc')),
        'okres':     safe_str(txt(elem, 'okres')),
    }

def find_child(elem, tag):
    for child in elem:
        if strip_ns(child.tag) == tag:
            return child
    return None

def find_all(elem, tag):
    return [child for child in elem if strip_ns(child.tag) == tag]

def pravni_forma_z_nazvu(filename):
    m = re.match(r'^([a-z0-9_]+)-(?:full|actual)-', Path(filename).name.lower())
    return m.group(1) if m else None

# ── Parser jednoho Subjektu ───────────────────────────────────────────────────

def parse_subjekt(elem, pravni_forma_kod, entity_rows, organ_rows, podil_rows):
    """
    Zpracuje jeden <Subjekt> element.
    Plni entity_rows, organ_rows, podil_rows.
    Vraci ICO (str) nebo None.
    """
    ico        = safe_str(txt(elem, 'ico'))
    nazev      = safe_str(txt(elem, 'nazev'), 490)
    zapis_d    = to_date(txt(elem, 'zapisDatum'))
    vymaz_d    = to_date(txt(elem, 'vymazDatum'))

    if not ico:
        return None

    # ── raw_or_entity ─────────────────────────────────────────────────────────
    entity_rows.append((
        ico, nazev, zapis_d, vymaz_d, safe_str(pravni_forma_kod),
    ))

    # ── raw_or_organy a raw_or_podily z udaju ─────────────────────────────────
    udaje_elem = find_child(elem, 'udaje')
    if udaje_elem is None:
        return ico

    for udaj in find_all(udaje_elem, 'Udaj'):
        zpracuj_udaj(udaj, ico, organ_rows, podil_rows, parent_udaj_typ=None)

    return ico


def zpracuj_udaj(udaj, ico, organ_rows, podil_rows, parent_udaj_typ):
    """Zpracuje jeden <Udaj> - bud prime nebo z podudaje."""

    udaj_typ_elem = find_child(udaj, 'udajTyp')
    udaj_typ_kod  = safe_str(txt(udaj_typ_elem, 'kod')) if udaj_typ_elem is not None else None
    udaj_typ_naz  = safe_str(txt(udaj_typ_elem, 'nazev')) if udaj_typ_elem is not None else None

    zapis_d  = to_date(txt(udaj, 'zapisDatum'))
    vymaz_d  = to_date(txt(udaj, 'vymazDatum'))

    # Angazma osoby (FO nebo PO)
    ho_elem = find_child(udaj, 'hodnotaUdaje')
    t_val   = safe_str(txt(ho_elem, 'T')) if ho_elem is not None else None

    if t_val in ('F', 'P') and udaj_typ_kod:
        funkce   = safe_str(txt(udaj, 'funkce'), 490)
        funkce_od = to_date(txt(udaj, 'funkceOd'))
        funkce_do = to_date(txt(udaj, 'funkceDo'))
        clenstvi_od = to_date(txt(udaj, 'clenstviOd'))
        clenstvi_do = to_date(txt(udaj, 'clenstviDo'))
        adr = parse_adresa(find_child(udaj, 'adresa'))
        osoba = find_child(udaj, 'osoba')

        if t_val == 'F' and osoba is not None:
            # Fyzicka osoba
            fo_jmeno    = safe_str(txt(osoba, 'jmeno'), 490)
            fo_prijmeni = safe_str(txt(osoba, 'prijmeni'), 490)
            fo_narozeni = to_date(txt(osoba, 'narozDatum'))
            fo_titul_p  = safe_str(txt(osoba, 'titulPred'))
            fo_titul_z  = safe_str(txt(osoba, 'titulZa'))
            fo_stat_naz = safe_str(txt(find_child(osoba, 'stat'), 'nazev')) if find_child(osoba, 'stat') is not None else None

            organ_rows.append((
                ico,
                udaj_typ_kod, udaj_typ_naz,
                funkce, funkce_od, funkce_do, clenstvi_od, clenstvi_do,
                zapis_d, vymaz_d,
                # FO
                fo_jmeno, fo_prijmeni, fo_titul_p, fo_titul_z,
                fo_narozeni, None, fo_stat_naz,
                adr.get('obec'), adr.get('cast'), adr.get('ulice'),
                adr.get('cislo_po'), adr.get('cislo_or'),
                adr.get('psc'), adr.get('okres'), adr.get('stat'),
                # PO
                None, None, None, None,
                # text
                None,
            ))

        elif t_val == 'P' and osoba is not None:
            # Pravnicka osoba
            po_ico   = safe_str(txt(osoba, 'ico'))
            po_nazev = safe_str(txt(osoba, 'nazev'), 490)
            po_euid  = safe_str(txt(osoba, 'euid'))
            po_reg   = safe_str(txt(osoba, 'regCislo'))

            organ_rows.append((
                ico,
                udaj_typ_kod, udaj_typ_naz,
                funkce, funkce_od, funkce_do, clenstvi_od, clenstvi_do,
                zapis_d, vymaz_d,
                # FO - vse None
                None, None, None, None, None, None, None,
                None, None, None, None, None, None, None, None,
                # PO
                po_ico, po_nazev, po_euid, po_reg,
                # text
                safe_str(txt(osoba, 'osobaText')),
            ))

    # Podil / vklad
    if ho_elem is not None and udaj_typ_kod:
        # Detekovat podil podle pritomnosti financnich hodnot
        vklad_elem  = find_child(ho_elem, 'vklad')
        souhrn_elem = find_child(ho_elem, 'souhrn')
        splaceni_elem = find_child(ho_elem, 'splaceni')

        if vklad_elem is not None or souhrn_elem is not None or \
           safe_str(txt(ho_elem, 'druhPodilu')) or safe_str(txt(ho_elem, 'pocet')):

            # Identifikace osoby ke ktere podil patri
            osoba = find_child(udaj, 'osoba')
            fo_prijmeni = fo_jmeno = fo_narozeni = po_ico_p = po_nazev_p = None
            if osoba is not None:
                t = safe_str(txt(find_child(udaj, 'hodnotaUdaje'), 'T'))
                if t == 'F':
                    fo_jmeno    = safe_str(txt(osoba, 'jmeno'), 490)
                    fo_prijmeni = safe_str(txt(osoba, 'prijmeni'), 490)
                    fo_narozeni = to_date(txt(osoba, 'narozDatum'))
                elif t == 'P':
                    po_ico_p   = safe_str(txt(osoba, 'ico'))
                    po_nazev_p = safe_str(txt(osoba, 'nazev'), 490)

            def dec_val(e, path):
                v = txt(e, path) if e is not None else None
                if not v:
                    return None
                try:
                    return float(v.replace(',', '.').replace(' ', ''))
                except (ValueError, TypeError):
                    return None

            podil_rows.append((
                ico,
                None,  # ORGAN_ID - plni se v transformaci
                udaj_typ_kod, udaj_typ_naz,
                zapis_d, vymaz_d,
                safe_str(txt(ho_elem, 'druhPodilu'), 190),
                safe_str(txt(ho_elem, 'podoba')),
                safe_str(txt(ho_elem, 'kmenovyList'), 490),
                to_int(txt(ho_elem, 'pocet')),
                to_int(txt(ho_elem, 'pocetClenu')),
                dec_val(vklad_elem,  'textValue') if vklad_elem is not None else None,
                safe_str(txt(vklad_elem, 'typ')) if vklad_elem is not None else None,
                dec_val(splaceni_elem, 'textValue') if splaceni_elem is not None else None,
                safe_str(txt(splaceni_elem, 'typ')) if splaceni_elem is not None else None,
                safe_str(txt(splaceni_elem, 'text'), 490) if splaceni_elem is not None else None,
                dec_val(souhrn_elem, 'textValue') if souhrn_elem is not None else None,
                safe_str(txt(souhrn_elem, 'typ')) if souhrn_elem is not None else None,
                safe_str(txt(ho_elem, 'spravce')),
                safe_str(txt(ho_elem, 'datRozhodnutihOs')),
                safe_str(txt(ho_elem, 'datVyveseni')),
                safe_str(txt(ho_elem, 'spisZnOs')),
                safe_str(txt(ho_elem, 'typZapisu/kod')),
                safe_str(txt(ho_elem, 'typZapisu/nazev')),
                safe_str(txt(ho_elem, 'typZapisu/aktivni')),
                safe_str(txt(ho_elem, 'textZaOsobu/value'), 490),
                safe_str(txt(ho_elem, 'textZruseni')),
                # identifikace osoby
                fo_prijmeni, fo_jmeno, fo_narozeni,
                po_ico_p, po_nazev_p,
            ))

    # Podudaje - rekurzivne
    podudaje_elem = find_child(udaj, 'podudaje')
    if podudaje_elem is not None:
        for pod in find_all(podudaje_elem, 'Udaj'):
            zpracuj_udaj(pod, ico, organ_rows, podil_rows,
                         parent_udaj_typ=udaj_typ_kod)


# ── SQL ───────────────────────────────────────────────────────────────────────

SQL_ENTITY = """
INSERT INTO [dbo].[raw_or_entity]
  ([ICO],[NAZEV],[ZAPIS_DATUM],[VYMAZ_DATUM],[PRAVNI_FORMA_KOD])
VALUES (?,?,?,?,?)
"""

SQL_ORGAN = """
INSERT INTO [dbo].[raw_or_organy]
  ([ENTITY_ID],[UDAJ_TYP_KOD],[UDAJ_TYP_NAZEV],
   [FUNKCE],[FUNKCE_OD],[FUNKCE_DO],[CLENSTVI_OD],[CLENSTVI_DO],
   [ZAPIS_DATUM],[VYMAZ_DATUM],
   [FO_JMENO],[FO_PRIJMENI],[FO_TITUL_PRED],[FO_TITUL_ZA],
   [FO_NAROZENI],[FO_STAT_KOD],[FO_STAT_NAZEV],
   [FO_BYD_OBEC],[FO_BYD_CAST_OBCE],[FO_BYD_ULICE],
   [FO_BYD_CISLO_PO],[FO_BYD_CISLO_OR],
   [FO_BYD_PSC],[FO_BYD_OKRES],[FO_BYD_STAT_NAZEV],
   [PO_ICO],[PO_NAZEV],[PO_EUID],[PO_REG_CISLO],
   [OSOBA_TEXT])
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

SQL_PODIL = """
INSERT INTO [dbo].[raw_or_podily]
  ([ENTITY_ID],[ORGAN_ID],[UDAJ_TYP_KOD],[UDAJ_TYP_NAZEV],
   [ZAPIS_DATUM],[VYMAZ_DATUM],
   [DRUH_PODILU],[PODOBA],[KMENOVY_LIST],[POCET],[POCET_CLENU],
   [VKLAD_HODNOTA],[VKLAD_TYP],[SPLACENI_HODNOTA],[SPLACENI_TYP],[SPLACENI_TEXT],
   [SOUHRN_HODNOTA],[SOUHRN_TYP],[SPRAVCE],
   [DAT_ROZHODNUTI],[DAT_VYVESENI],[SPIS_ZN_INSOLVENCE],
   [TYP_ZAPISU_KOD],[TYP_ZAPISU_NAZEV],[TYP_ZAPISU_AKTIVNI],
   [ZASTOUPENI_TEXT],[ZRUSENI_TEXT],
   [FO_PRIJMENI],[FO_JMENO],[FO_NAROZENI],[PO_ICO],[PO_NAZEV])
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


# ── Hlavni logika ─────────────────────────────────────────────────────────────

def process_folder(folder, conn_string, batch_size):
    folder_path   = Path(folder)
    xml_files     = sorted(folder_path.glob("*.xml"))
    processed_dir = (folder_path / ".." / "processed").resolve()
    processed_dir.mkdir(exist_ok=True)

    if not xml_files:
        log(f"Zadne XML soubory v {folder}")
        return

    log(f"Nalezeno {len(xml_files)} souboru v {folder}")

    conn   = pyodbc.connect(conn_string, autocommit=False)
    cursor = conn.cursor()
    cursor.fast_executemany = False

    # Preskocit jiz zpracovane soubory (podle existujicich ICO)
    log("Nacitam existujici ICO z DB...")
    cursor.execute("SELECT [ICO] FROM [dbo].[raw_or_entity]")
    existing_ico = {row[0] for row in cursor.fetchall()}
    log(f"V DB je {len(existing_ico):,} existujicich entit")

    total_entity = total_organ = total_podil = 0
    total_souboru = 0

    for file_idx, xml_path in enumerate(xml_files, 1):
        log(f"[{file_idx}/{len(xml_files)}] {xml_path.name}")

        pravni_forma = pravni_forma_z_nazvu(xml_path.name)

        entity_rows = []
        organ_rows  = []
        podil_rows  = []

        try:
            in_subjekt = False
            context = ET.iterparse(str(xml_path), events=('start', 'end'))

            for event, elem in context:
                tag = strip_ns(elem.tag)

                if event == 'start' and tag == 'Subjekt':
                    in_subjekt = True

                elif event == 'end' and tag == 'Subjekt' and in_subjekt:
                    in_subjekt = False

                    ico = parse_subjekt(elem, pravni_forma,
                                        entity_rows, organ_rows, podil_rows)

                    # Flush kdyz je davka plna
                    if len(entity_rows) >= batch_size:
                        entity_ids = flush_entity(cursor, entity_rows)
                        flush_organ(cursor, organ_rows, entity_ids)
                        flush_podil(cursor, podil_rows, entity_ids)
                        total_entity += len(entity_rows)
                        total_organ  += len(organ_rows)
                        total_podil  += len(podil_rows)
                        entity_rows = []
                        organ_rows  = []
                        podil_rows  = []

                    elem.clear()

                elif not in_subjekt:
                    elem.clear()

            # Zbytek
            if entity_rows:
                entity_ids = flush_entity(cursor, entity_rows)
                flush_organ(cursor, organ_rows, entity_ids)
                flush_podil(cursor, podil_rows, entity_ids)
                total_entity += len(entity_rows)
                total_organ  += len(organ_rows)
                total_podil  += len(podil_rows)

            conn.commit()
            total_souboru += 1
            log(f"  -> entity:{len(entity_rows) if not entity_rows else total_entity}  commit OK")
            shutil.move(str(xml_path), processed_dir / xml_path.name)

        except Exception as e:
            conn.rollback()
            log(f"CHYBA souboru {xml_path.name}: {e}")
            import traceback
            traceback.print_exc()

    cursor.close()
    conn.close()

    log("=" * 60)
    log(f"Hotovo.")
    log(f"  Souboru:  {total_souboru:>10,}")
    log(f"  Entity:   {total_entity:>10,}")
    log(f"  Organy:   {total_organ:>10,}")
    log(f"  Podily:   {total_podil:>10,}")


def flush_entity(cursor, rows):
    """Vlozi entity a vrati dict ICO -> ID."""
    # Vlozit jen nove (IF NOT EXISTS)
    for row in rows:
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM [dbo].[raw_or_entity] WHERE [ICO]=?)
            """ + SQL_ENTITY, (row[0],) + row)

    # Nacist ID pro vsechny ICO v davce
    icos = [r[0] for r in rows if r[0]]
    if not icos:
        return {}
    placeholders = ','.join(['?'] * len(icos))
    cursor.execute(
        f"SELECT [ICO],[ID] FROM [dbo].[raw_or_entity] WHERE [ICO] IN ({placeholders})",
        icos
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def flush_organ(cursor, rows, entity_ids):
    if not rows:
        return
    insert_rows = []
    for row in rows:
        entity_id = entity_ids.get(row[0])  # row[0] = ICO
        if entity_id:
            insert_rows.append((entity_id,) + row[1:])
    if insert_rows:
        cursor.executemany(SQL_ORGAN, insert_rows)


def flush_podil(cursor, rows, entity_ids):
    if not rows:
        return
    insert_rows = []
    for row in rows:
        entity_id = entity_ids.get(row[0])
        if entity_id:
            insert_rows.append((entity_id,) + row[1:])
    if insert_rows:
        cursor.executemany(SQL_PODIL, insert_rows)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAW import OR -> Z_ORstagg")
    parser.add_argument("--folder", default=DEFAULT_FOLDER)
    parser.add_argument("--batch",  type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    t0 = datetime.now()
    log("=== import_or.py ===")
    process_folder(args.folder, CONN_STRING, args.batch)
    log(f"Celkovy cas: {datetime.now() - t0}")
