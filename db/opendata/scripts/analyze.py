"""
analyze.py - Univerzalni analyzator XML souboru pro staging import
================================================================
Pouziti:
    python analyze.py --folder "E:/1_OPENDATA/OBCH_REJSTRIK/new" --source OR
    python analyze.py --folder "E:/1_OPENDATA/STK/new" --source STK
    python analyze.py --folder "E:/1_OPENDATA/RUIAN/new" --source RUIAN

Vystup (do stejne slozky jako skript):
    analysis_OR.json            - surova analyza
    create_tables_OR.sql        - DDL pro staging tabulky
    OR.cfg                      - konfigurace pro import.py (sablona)

Zavislosti: zadne (jen stdlib)
"""

import xml.etree.ElementTree as ET
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, date
from collections import Counter, defaultdict

# ── Pomocne funkce ────────────────────────────────────────────────────────────

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):
    print(f"{ts()}  {msg}", flush=True)

def strip_ns(tag):
    """Odstrani XML namespace z nazvu tagu: {ns}tag -> tag"""
    return re.sub(r'^\{[^}]+\}', '', tag)

def detect_type(samples):
    """
    Z vzorku hodnot navrhne SQL typ.
    Vraci (sql_type, max_len, anomalie)
    """
    if not samples:
        return "nvarchar(100)", 0, []

    max_len = max(len(str(s)) for s in samples)
    anomalie = []

    # Zkusit date
    date_ok = 0
    for s in samples[:200]:
        try:
            datetime.strptime(str(s).strip()[:10], "%Y-%m-%d")
            date_ok += 1
        except ValueError:
            pass
    if date_ok / len(samples[:200]) > 0.95:
        return "date", 10, anomalie

    # Zkusit datetime
    dt_ok = 0
    for s in samples[:200]:
        sv = str(s).strip()
        if len(sv) >= 16 and 'T' in sv:
            try:
                datetime.strptime(sv[:16], "%Y-%m-%dT%H:%M")
                dt_ok += 1
            except ValueError:
                pass
    if dt_ok / len(samples[:200]) > 0.95:
        return "datetime2", 27, anomalie

    # Zkusit int
    int_ok = 0
    for s in samples[:200]:
        try:
            int(str(s).strip())
            int_ok += 1
        except ValueError:
            pass
    if int_ok / len(samples[:200]) > 0.98:
        max_val = max(abs(int(str(s).strip())) for s in samples[:200]
                      if str(s).strip().lstrip('-').isdigit())
        if max_val < 2147483647:
            return "int", 11, anomalie
        return "bigint", 20, anomalie

    # Zkusit decimal
    dec_ok = 0
    for s in samples[:200]:
        try:
            float(str(s).strip().replace(',', '.'))
            dec_ok += 1
        except ValueError:
            pass
    if dec_ok / len(samples[:200]) > 0.98:
        return "decimal(18,6)", 20, anomalie

    # Detekovat anomalie v textovych hodnotach
    for s in samples:
        sv = str(s)
        # Prilis dlouhe hodnoty
        if len(sv) > 500:
            anomalie.append(f"DLOUHY_TEXT ({len(sv)} zn): {sv[:80]}...")
        # Ocekavane PSC ale obsahuje text
        if re.match(r'^\d{3}\s?\d{2}$', sv):
            pass  # OK
        elif re.search(r'\d{3}.*[a-zA-Z]{3,}', sv) and len(sv) > 10:
            anomalie.append(f"MOZNA_SPATNE_PSC: {sv[:60]}")
        # ICO - nespravny format
        if re.match(r'^[A-Za-z].*\d', sv) and 5 < len(sv) < 15:
            anomalie.append(f"MOZNE_SPATNE_ICO: {sv[:30]}")

    # Urcit velikost nvarchar
    if max_len <= 20:
        sql_type = "nvarchar(50)"
    elif max_len <= 50:
        sql_type = "nvarchar(100)"
    elif max_len <= 100:
        sql_type = "nvarchar(200)"
    elif max_len <= 250:
        sql_type = "nvarchar(500)"
    elif max_len <= 500:
        sql_type = "nvarchar(1000)"
    else:
        sql_type = "nvarchar(max)"

    return sql_type, max_len, anomalie[:5]  # max 5 anomalii na pole

def safe_col_name(path):
    """Prevede XPath-like cestu na bezpecny nazev SQL sloupce."""
    name = re.sub(r'[^a-zA-Z0-9_]', '_', path)
    name = re.sub(r'_+', '_', name).strip('_')
    if name and name[0].isdigit():
        name = 'F_' + name
    return name[:128]

# ── Analyza XML struktury ─────────────────────────────────────────────────────

def detect_record_element(xml_files, max_files=10):
    """
    Projde prvnich max_files souboru a detekuje nejpravdepodobnejsi
    record element - najde opakujici se element na libovolne urovni.
    Vraci (record_tag, sub_record_tag_or_None, namespace)
    """
    log("  Detekuji strukturu XML...")
    namespace = ""
    # (depth, tag) -> count
    depth_counts = defaultdict(Counter)
    max_depth_seen = 0

    for xml_path in xml_files[:max_files]:
        depth = 0
        for event, elem in ET.iterparse(str(xml_path), events=('start', 'end')):
            if not namespace and '{' in elem.tag:
                ns_match = re.match(r'^\{([^}]+)\}', elem.tag)
                if ns_match:
                    namespace = ns_match.group(1)
            if event == 'start':
                depth += 1
                max_depth_seen = max(max_depth_seen, depth)
                depth_counts[depth][strip_ns(elem.tag)] += 1
            else:
                depth -= 1
                elem.clear()

    log(f"  Namespace: {namespace or 'zadny'}")

    # Najit record element = opakujici se element s nejvetsim poctem vyskytu
    # ktery neni root (depth=1) a neni listovy (ma deti)
    # Heuristika: hledame element kde count >> 1 a je na nejnizsi takove urovni
    best_record = None
    best_count = 1
    best_depth = 0

    for d in range(2, max_depth_seen + 1):
        for tag, cnt in depth_counts[d].items():
            if cnt > best_count:
                best_count = cnt
                best_record = tag
                best_depth = d

    # Sub-record = nejcastejsi element na urovni best_depth+1 nebo best_depth+2
    # ktery je cetnejsi nez record (= vice sub-zaznamu nez hlavnich zaznamu)
    sub_record_tag = None
    for d in range(best_depth + 1, min(best_depth + 3, max_depth_seen + 1)):
        for tag, cnt in depth_counts[d].most_common(3):
            if cnt > best_count * 2:
                sub_record_tag = tag
                break
        if sub_record_tag:
            break

    log(f"  Hierarchie (top 3 na kazde urovni):")
    for d in range(1, min(max_depth_seen + 1, 7)):
        top = depth_counts[d].most_common(3)
        if top:
            log(f"    Uroven {d}: {top}")

    # Lepsi heuristika: record element je nejcastejsi element
    # ktery se opakuje ale NE prilis - tj. neni zanoreny atribut/hodnota
    # Kandidati: elementy s count mezi 10 a 500000, preferujeme nizsi uroven
    candidates = []
    for d in range(2, max_depth_seen + 1):
        for tag, cnt in depth_counts[d].most_common(5):
            if cnt >= 5:  # aspon 5 vyskytu
                candidates.append((d, tag, cnt))

    # Vybrat "nejlepsiho" kandadata:
    # Preferujeme element na nejnizsi urovni kde je cetnost > 1
    # a zaroven neni tak cetny ze by byl jen listovou hodnotou
    # Heuristika: hledame "zlomovy bod" kde count naroste
    best_record = None
    best_depth = 0
    best_count = 0

    prev_max = 1
    for d in range(2, max_depth_seen + 1):
        top = depth_counts[d].most_common(1)
        if not top:
            continue
        tag, cnt = top[0]
        # Pokud je na teto urovni element >5x cetnejsi nez na predchozi -> record
        if cnt > prev_max * 3 and cnt >= 5:
            best_record = tag
            best_depth = d
            best_count = cnt
            # Nekoncime - hledame dale zda neni lepsi sub-record
        prev_max = max(prev_max, cnt)

    # Sub-record: na urovni best_depth+1 az best_depth+2
    # element cetnejsi nez record
    sub_record_tag = None
    for d in range(best_depth + 1, min(best_depth + 3, max_depth_seen + 1)):
        for tag, cnt in depth_counts[d].most_common(3):
            if cnt > best_count * 1.5 and tag != best_record:
                sub_record_tag = tag
                break
        if sub_record_tag:
            break

    if best_record:
        log(f"  Detekovan record element: <{best_record}> ({best_count:,}x na urovni {best_depth})")
    else:
        log(f"  VAROVANI: Nepodarilo se automaticky detekovat record element")
        log(f"  Nastavte record_element rucne v .cfg souboru")
        best_record = candidates[0][1] if candidates else "UNKNOWN"
        best_depth = candidates[0][0] if candidates else 2
        best_count = candidates[0][2] if candidates else 0

    if sub_record_tag:
        log(f"  Detekovan sub-record element: <{sub_record_tag}>")

    return best_record, sub_record_tag, namespace


def collect_field(path, val, field_stats, max_samples=500):
    """Prida hodnotu do statistik pole."""
    if path not in field_stats:
        field_stats[path] = {'count': 0, 'samples': [], 'null_count': 0}
    field_stats[path]['count'] += 1
    v = (str(val) if val is not None else "").strip()
    if v:
        if len(field_stats[path]['samples']) < max_samples:
            field_stats[path]['samples'].append(v)
    else:
        field_stats[path]['null_count'] += 1

def analyze_record(elem, prefix="", field_stats=None, depth=0, max_depth=6,
                   skip_tag=None):
    """
    Rekurzivne projde element a sbira statistiky pro kazde pole.
    skip_tag: preskoci elementy s timto jmenem (pro oddeleni hlavni/sub tabulky)
    """
    if field_stats is None:
        field_stats = {}
    if depth > max_depth:
        return field_stats

    tag = strip_ns(elem.tag)

    # Preskocit sub-record elementy v hlavnim zaznamu
    if skip_tag and tag == skip_tag and depth > 0:
        return field_stats

    path = f"{prefix}.{tag}" if prefix else tag

    # Atributy elementu
    for attr_name, attr_val in elem.attrib.items():
        attr_path = f"{path}@{strip_ns(attr_name)}"
        collect_field(attr_path, attr_val, field_stats)

    # Deti
    children = list(elem)
    if not children:
        # Listovy element - ulozit hodnotu
        collect_field(path, elem.text, field_stats)
    else:
        # Nelistovy element - rekurze
        for child in children:
            analyze_record(child, path, field_stats, depth + 1, max_depth, skip_tag)

    return field_stats


def analyze_folder(folder, source_name, max_samples=1000, record_override=None, subrecord_override=None):
    """
    Hlavni analyza - projde vsechny XML soubory ve slozce.
    """
    folder_path = Path(folder)
    xml_files = sorted(folder_path.glob("*.xml"))

    if not xml_files:
        log(f"CHYBA: Zadne XML soubory v {folder}")
        return None

    log(f"Nalezeno {len(xml_files)} XML souboru v {folder}")

    # ── Krok 1: Detekce struktury ─────────────────────────────────────────────
    log("Krok 1/3: Detekce XML struktury...")
    record_tag, sub_record_tag, namespace = detect_record_element(xml_files)
    # Rucni override
    if record_override:
        log(f"  OVERRIDE record element: <{record_override}>")
        record_tag = record_override
    if subrecord_override:
        log(f"  OVERRIDE sub-record element: <{subrecord_override}>")
        sub_record_tag = subrecord_override

    if not record_tag:
        log("CHYBA: Nepodarilo se detekovat record element")
        return None

    # ── Krok 2: Hloubkova analyza poli ───────────────────────────────────────
    log(f"Krok 2/3: Analyza obsahu poli (record=<{record_tag}>)...")

    main_stats = {}     # statistiky hlavniho zaznamu
    sub_stats = {}      # statistiky pod-zaznamu

    total_records = 0
    total_sub_records = 0
    file_stats = []     # statistiky per soubor

    for file_idx, xml_path in enumerate(xml_files, 1):
        log(f"  [{file_idx}/{len(xml_files)}] {xml_path.name}")

        file_records = 0
        file_sub_records = 0

        try:
            # Pouzit 'start' + 'end' aby elementy nebyly cisteny pred analyzou
            context = ET.iterparse(str(xml_path), events=('start', 'end'))
            in_record = False
            in_sub = False
            current_record = None

            for event, elem in context:
                tag = strip_ns(elem.tag)

                if event == 'start':
                    if tag == record_tag and not in_record:
                        in_record = True
                        current_record = elem
                    elif sub_record_tag and tag == sub_record_tag and in_record:
                        in_sub = True

                elif event == 'end':
                    if sub_record_tag and tag == sub_record_tag and in_sub:
                        in_sub = False
                        file_sub_records += 1
                        total_sub_records += 1
                        if total_sub_records <= max_samples * 5:
                            analyze_record(elem, "", sub_stats)
                        # Vymazat sub-element z pameti ale NECHAT ho v rodicovskem
                        # (nezavolame elem.clear() - jen oznacime jako zpracovany)

                    elif tag == record_tag and in_record:
                        in_record = False
                        file_records += 1
                        total_records += 1
                        if total_records <= max_samples:
                            analyze_record(elem, "", main_stats,
                                           skip_tag=sub_record_tag)
                        current_record = None
                        elem.clear()  # Nyni bezpecne vymazat

                    elif not in_record:
                        elem.clear()

        except ET.ParseError as e:
            log(f"  PARSE CHYBA v {xml_path.name}: {e}")

        file_stats.append({
            "soubor": xml_path.name,
            "velikost_mb": round(xml_path.stat().st_size / 1024 / 1024, 2),
            "zaznamu": file_records,
            "sub_zaznamu": file_sub_records,
        })

    log(f"  Celkem zaznamu: {total_records:,}")
    if sub_record_tag:
        log(f"  Celkem sub-zaznamu: {total_sub_records:,}")

    # ── Krok 3: Vyhodnoceni typu a anomalii ───────────────────────────────────
    log("Krok 3/3: Vyhodnoceni typu sloupcu a anomalii...")

    def vyhodnotit_stats(stats, total):
        result = {}
        for path, info in sorted(stats.items()):
            sql_type, max_len, anomalie = detect_type(info['samples'])
            null_pct = round(info['null_count'] / max(info['count'], 1) * 100, 1)
            fill_pct = round((info['count'] - info['null_count']) / max(total, 1) * 100, 1)
            col_name = safe_col_name(path)
            result[path] = {
                "col_name":    col_name,
                "sql_type":    sql_type,
                "max_len":     max_len,
                "count":       info['count'],
                "null_pct":    null_pct,
                "fill_pct":    fill_pct,
                "vzorky":      info['samples'][:5],
                "anomalie":    anomalie,
                "include":     True,   # default: zahrnout do importu
            }
        return result

    main_fields = vyhodnotit_stats(main_stats, total_records)
    sub_fields  = vyhodnotit_stats(sub_stats, total_sub_records) if sub_stats else {}

    # ── Sestaveni vysledku ────────────────────────────────────────────────────
    result = {
        "meta": {
            "source":          source_name,
            "folder":          str(folder),
            "analyzed_at":     datetime.now().isoformat(),
            "xml_files":       len(xml_files),
            "total_size_mb":   round(sum(f["velikost_mb"] for f in file_stats), 1),
            "namespace":       namespace,
            "record_element":  record_tag,
            "sub_record_element": sub_record_tag,
            "total_records":   total_records,
            "total_sub_records": total_sub_records,
        },
        "soubory": file_stats,
        "hlavni_zaznam": main_fields,
        "sub_zaznam":    sub_fields,
    }

    return result


# ── Generovani vystupnich souboru ─────────────────────────────────────────────

def generate_ddl(analysis, out_path):
    """Generuje CREATE TABLE SQL z vysledku analyzy."""
    src = analysis['meta']['source']
    record = analysis['meta']['record_element']
    sub    = analysis['meta']['sub_record_element']

    lines = []
    lines.append(f"-- DDL vygenerovano: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"-- Zdroj: {src}  |  Record element: <{record}>")
    lines.append(f"-- Upravte typy/nazvy dle potreby pred spustenim")
    lines.append(f"-- Celkem zaznamu k importu: {analysis['meta']['total_records']:,}")
    lines.append("")
    lines.append("USE [Z_ORstagg]")
    lines.append("GO")
    lines.append("")

    def table_ddl(table_name, fields, total):
        t = []
        t.append(f"-- {total:,} zaznamu")
        t.append(f"CREATE TABLE [dbo].[{table_name}] (")
        t.append(f"    [ID] bigint NOT NULL IDENTITY(1,1),")

        # Anomalie jako komentar
        anomalie_fields = [(p, f) for p, f in fields.items() if f['anomalie']]
        if anomalie_fields:
            t.append(f"    -- POZOR: {len(anomalie_fields)} poli s detekovanymi anomaliemi (viz JSON)")

        for path, f in fields.items():
            if not f['include']:
                t.append(f"    -- EXCLUDED: [{f['col_name']}]  {f['sql_type']}")
                continue
            anom = "  -- !! ANOMALIE" if f['anomalie'] else ""
            null_info = f"  -- fill {f['fill_pct']}%"
            nullable = "NULL" if f['null_pct'] > 0 else "NOT NULL"
            t.append(f"    [{f['col_name']}] {f['sql_type']} {nullable},{anom}{null_info}")

        t.append(f"    CONSTRAINT [PK_{table_name}] PRIMARY KEY CLUSTERED ([ID])")
        t.append(f")")
        t.append("GO")
        t.append("")
        return t

    # Hlavni tabulka
    main_table = f"raw_{src.lower()}_main"
    lines += table_ddl(main_table, analysis['hlavni_zaznam'],
                       analysis['meta']['total_records'])

    # Sub-zaznam tabulka
    if sub and analysis['sub_zaznam']:
        sub_table = f"raw_{src.lower()}_detail"
        lines.append(f"-- Sub-zaznam: <{sub}>")
        # Pridat FK na hlavni tabulku
        sub_fields_with_fk = {
            f"PARENT_ID": {
                "col_name": "PARENT_ID", "sql_type": "bigint",
                "null_pct": 0, "fill_pct": 100,
                "anomalie": [], "include": True,
            }
        }
        sub_fields_with_fk.update(analysis['sub_zaznam'])
        lines += table_ddl(sub_table, sub_fields_with_fk,
                           analysis['meta']['total_sub_records'])

    out_path.write_text("\n".join(lines), encoding='utf-8')
    log(f"DDL ulozeno: {out_path}")


def generate_cfg(analysis, out_path):
    """Generuje .cfg sablonu pro import.py."""
    src  = analysis['meta']['source']
    meta = analysis['meta']

    lines = [
        f"# Konfigurace importu pro zdroj: {src}",
        f"# Vygenerovano: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"# Upravte dle potreby a spustte import.py",
        "",
        "[source]",
        f"name         = {src}",
        f"folder       = {meta['folder']}",
        f"format       = xml",
        "",
        "[xml]",
        f"record_element    = {meta['record_element']}",
        f"sub_record_element = {meta['sub_record_element'] or ''}",
        f"namespace          = {meta['namespace'] or ''}",
        "",
        "[database]",
        f"server       = HPZ4",
        f"database     = Z_ORstagg",
        f"main_table   = raw_{src.lower()}_main",
        f"sub_table    = raw_{src.lower()}_detail",
        f"batch_size   = 2000",
        "",
        "[update]",
        f"# full = uplne zneni (vse znovu), actual = jen platne (prirustkove)",
        f"update_type  = full",
        f"frequency    = monthly",
        f"source_url   = ",
        "",
        "# Vybrane sloupce pro import (odkomentujte radky pro vylouceni):",
        "# Upravte v analysis_*.json pole 'include': false pro vylouceni sloupce",
        f"[columns_main]",
    ]

    for path, f in analysis['hlavni_zaznam'].items():
        status = "include" if f['include'] else "# exclude"
        anom = "  # ANOMALIE" if f['anomalie'] else ""
        lines.append(f"{status} = {f['col_name']}{anom}")

    if analysis['sub_zaznam']:
        lines.append("")
        lines.append(f"[columns_detail]")
        for path, f in analysis['sub_zaznam'].items():
            status = "include" if f['include'] else "# exclude"
            anom = "  # ANOMALIE" if f['anomalie'] else ""
            lines.append(f"{status} = {f['col_name']}{anom}")

    out_path.write_text("\n".join(lines), encoding='utf-8')
    log(f"CFG ulozeno: {out_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XML analyza pro staging import")
    parser.add_argument("--folder",  required=True,
                        help="Slozka s XML soubory")
    parser.add_argument("--source",  required=True,
                        help="Nazev zdroje (OR, STK, RUIAN...)")
    parser.add_argument("--samples", type=int, default=1000,
                        help="Max pocet zaznamu pro analyzu (default 1000)")
    parser.add_argument("--record",  default=None,
                        help="Record element (override auto-detekce), napr. --record Mereni")
    parser.add_argument("--subrecord", default=None,
                        help="Sub-record element (override), napr. --subrecord Udaj")
    parser.add_argument("--out",     default=None,
                        help="Vystupni slozka (default: slozka skriptu)")
    args = parser.parse_args()

    t0 = datetime.now()
    log(f"=== analyze.py | zdroj={args.source} | slozka={args.folder} ===")

    result = analyze_folder(args.folder, args.source, args.samples, args.record, args.subrecord)

    if result:
        out_dir = Path(args.out) if args.out else Path(__file__).parent
        out_dir.mkdir(exist_ok=True)

        # JSON
        json_path = out_dir / f"analysis_{args.source}.json"
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8'
        )
        log(f"JSON ulozeno: {json_path}")

        # DDL
        sql_path = out_dir / f"create_tables_{args.source}.sql"
        generate_ddl(result, sql_path)

        # CFG
        cfg_path = out_dir / f"{args.source}.cfg"
        generate_cfg(result, cfg_path)

        # Souhrn anomalii
        log("")
        log("=== SOUHRN ANOMALII ===")
        vsechna = list(result['hlavni_zaznam'].items()) + list(result['sub_zaznam'].items())
        anom_count = 0
        for path, f in vsechna:
            if f['anomalie']:
                log(f"  {f['col_name']}: {f['anomalie'][0]}")
                anom_count += 1
        if anom_count == 0:
            log("  Zadne anomalie detekovany")

        log("")
        log("=== SOUHRN ===")
        log(f"  Souboru:          {result['meta']['xml_files']:>8,}")
        log(f"  Celk. velikost:   {result['meta']['total_size_mb']:>8.1f} MB")
        log(f"  Zaznamu:          {result['meta']['total_records']:>8,}")
        if result['meta']['sub_record_element']:
            log(f"  Sub-zaznamu:      {result['meta']['total_sub_records']:>8,}")
        log(f"  Pole hlavni tab:  {len(result['hlavni_zaznam']):>8,}")
        log(f"  Pole detail tab:  {len(result['sub_zaznam']):>8,}")
        log(f"  Cas analyzy:      {datetime.now() - t0}")
        log("")
        log(f"Dalsi krok: zkontroluj {args.source}.cfg a uprav 'include/exclude' sloupce")
        log(f"Pak uprav create_tables_{args.source}.sql a spust import.py")
