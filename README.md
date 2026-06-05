opendata-pipeline
Projekt pro zpracování českých veřejných (open) dat do staging databází na SQL Serveru 2022.
Autor: Rudolf · Prostředí: HPZ4 (SQL Server 2022 Developer) · Python 3.13
---
Architektura
Databáze
Databáze	Účel
`opendata`	Sdílené funkce, procedury, číselníky, referenční data
`Z_ORstagg`	Staging – Obchodní rejstřík (OR), ~500 XML souborů
`Z_STKstagg`	Staging – STK a emise, ~6 000 XML souborů
`Z_RAstagg`	Staging – Registr vozidel (CSV 16 GB + majitelé 6 GB)
`Z_DIVstagg`	Staging – různé menší datasety bez vlastní DB
Tok dat
```
Zdroj (web/API)
    │
    ▼
E:\1_OPENDATA\<AGENDA>\download\     ← stažená surová data (zůstávají trvale)
    │
    │  rozbalení / příprava
    ▼
E:\1_OPENDATA\<AGENDA>\new\          ← připraveno k importu
    │
    │  Python import script
    ▼
Z_<AGENDA>stagg                      ← staging DB (raw, bez transformace)
    │
    │  SQL funkce z opendata DB
    ▼
Čištění / validace / standardizace
    │
    ▼
Produkční tabulky (budoucí fáze)
```
Po úspěšném importu Python script přesune soubory do:
`E:\1_OPENDATA\<AGENDA>\processed\`
Principy stagingu
Staging databáze jsou read-only při běžném provozu – plní se v noci
Žádná transformační logika ve staging – pouze věrný přepis zdroje do tabulek
Zachovává se plná historie (ZapisDatum / VymazDatum)
Data v staging mohou zůstávat trvale – usnadňují detekci změn při dalším importu
---
Databáze `opendata`
Centrální databáze pro sdílenou logiku. Obsahuje:
Číselníky a referenční tabulky
Tabulka	Obsah
`cfg_Staty`	Státy světa – ISO kódy, tel. předvolby, DIC prefix, PSC formát, IsEU, IsEURzone
`cfg_Formy`	Právní formy podnikajících subjektů (dle ARES/OR) vč. historických
`cfg_Jmena`	Referenční seznam jmen dle ČSÚ (četnost, pohlaví, pořadí)
`cfg_Prijmeni`	Referenční seznam příjmení dle ČSÚ (četnost, pohlaví, okres)
`cfg_Tituly`	Akademické a profesní tituly – normalizované formy
`dim_Obce`	RUIAN – seznam obcí ČR (6 258 záznamů)
`dim_Okresy`	RUIAN – okresy
`dim_Kraje`	RUIAN – kraje
`dim_AdresniMista`	RUIAN – všechna adresní místa ČR (čísla popisná)
`dim_Zeme`	Číselník zemí vč. alpha kódů, tel. předvoleb, IBAN
`stg_kontakty`	Výstup usp_ExtractContacts – normalizované kontakty ze zdrojů
Funkce
Funkce	Popis
`fn_CleanString`	Základní technické čištění (control chars, NBSP, BOM, vícenásobné mezery)
`fn_CleanStringExt`	Rozšířené čištění + Unicode normalizace (en/em-dash, typografické uvozovky)
`fn_SplitContacts`	Rozdělení vícehodnotového pole na tokeny podle oddělovačů
`fn_NormalizeEmail`	Normalizace emailu dle RFC 5321, validace TLD
`fn_NormalizePhone`	Normalizace tel. čísla do formátu E.164
`fn_NormalizeUrl`	Normalizace URL (https://, trailing /, markdown extrakce)
`fn_NormalizeICO`	(připravuje se) Normalizace a validace IČO (kontrolní číslice)
`fn_NormalizeDIC`	(připravuje se) Normalizace DIČ dle státu (prefix z cfg_Staty)
`fn_NormalizeDate`	(připravuje se) Normalizace datumu z různých textových formátů
`fn_ParseTitle`	(připravuje se) Extrakce titulů z pole FO_TitulPred/Za, separace dat narození a RC
`fn_NormalizeName`	(připravuje se) Title Case + lookup v cfg_Jmena / cfg_Prijmeni
Procedury
Procedura	Popis
`usp_ExtractContacts`	Orchestrace: extrahuje kontakty z libovolné zdrojové tabulky do `stg_kontakty`
---
Databáze `Z_ORstagg` – Obchodní rejstřík
Zdroj
https://dataor.justice.cz – XML soubory rozdělené po krajích a typech subjektů.
Pojmenování souborů: `<forma>-full-<kraj>-<rok>.xml`
Příklady: `as-full-plzen-2026.xml`, `sro-full-stredocesky-2026.xml`
Tabulky
Tabulka	Klíč	Popis
`src_OR_Entity`	ICO	Jeden řádek na právní subjekt. Název, forma, stav.
`src_OR_Udaje`	ID (auto)	Každý zápis/výmaz v OR – plná historie. FK na ICO.
Sloupce src_OR_Udaje – osoby (FO)
```
FO_Jmeno       – křestní jméno (UPPERCASE z OR)
FO_Prijmeni    – příjmení
FO_TitulPred   – titul před jménem (obsahuje i RC, datumy, pořadová čísla – viz fn_ParseTitle)
FO_TitulZa     – titul za jménem (obsahuje i datumy narození, "nar.", profese)
FO_DatNar      – datum narození (datetime, většinou čistý)
FO_StatKod     – kód státu ('cz', 'de', 'sk', ...)
```
Import script
`python/or_import.py`
Čte XML soubory z `E:\1_OPENDATA\OBCH_REJSTRIK\new\`
Commituje v dávkách po 500 záznamech
Po úspěchu přesouvá soubor do `\processed\`
`fast_executemany=False` (prevence truncation při pyodbc)
---
Databáze `Z_STKstagg` – STK a emise
(import script v přípravě)
Zdroj: https://www.mdcr.cz/Dokumenty/Silnicni-doprava/STK
Formát: ~6 000 XML souborů
---
Databáze `Z_RAstagg` – Registr vozidel
(import script v přípravě)
Zdroj: https://www.mdcr.cz/Statistiky/Silnicni-doprava/Registr-motorovych-vozidel
Formát: 2 CSV soubory (vozidla ~16 GB, majitelé ~6 GB)
Strategie: SQL Server BULK INSERT nebo BCP přes staging filegroup
---
Nastavení databází (staging)
Všechny staging DB jsou nastaveny pro rychlé načítání:
```sql
RECOVERY SIMPLE
DELAYED_DURABILITY = FORCED
AUTO_SHRINK OFF
AUTO_CREATE_STATISTICS ON
AUTO_UPDATE_STATISTICS ON
-- Datový soubor: SIZE=512MB, FILEGROWTH=256MB
-- Staging filegroup: SIZE=25GB, FILEGROWTH=2GB
-- Log: SIZE=2GB, MAXSIZE=50GB, FILEGROWTH=512MB
```
---
Struktura složek v repozitáři
```
opendata-pipeline/
├── README.md
├── db/
│   ├── opendata/
│   │   ├── tables/
│   │   │   ├── cfg_Staty.sql
│   │   │   ├── cfg_Formy.sql
│   │   │   ├── cfg_Jmena.sql
│   │   │   ├── cfg_Prijmeni.sql
│   │   │   └── cfg_Tituly.sql
│   │   ├── functions/
│   │   │   ├── fn_CleanString.sql
│   │   │   ├── fn_CleanStringExt.sql
│   │   │   ├── fn_SplitContacts.sql
│   │   │   ├── fn_NormalizeEmail.sql
│   │   │   ├── fn_NormalizePhone.sql
│   │   │   └── fn_NormalizeUrl.sql
│   │   └── procedures/
│   │       └── usp_ExtractContacts.sql
│   ├── Z_ORstagg/
│   │   ├── tables/
│   │   │   ├── src_OR_Entity.sql
│   │   │   └── src_OR_Udaje.sql
│   │   └── procedures/
│   └── Z_STKstagg/
│       └── tables/
├── python/
│   ├── or_import.py
│   └── stk_import.py       ← připravuje se
└── docs/
    └── zdroje.md            ← přehled zdrojů, frekvence aktualizace, kontakty
```
---
Jak pracovat s Claude
Jakmile je soubor v repozitáři, lze ho sdílet přes raw URL:
```
https://raw.githubusercontent.com/<tvuj-ucet>/opendata-pipeline/main/db/opendata/functions/fn_CleanString.sql
```
Claude umí číst raw GitHub URL přímo – není třeba kopírovat obsah do chatu.
Doporučený workflow
Změníš nebo vytvoříš SQL soubor lokálně
Commitneš do GitHubu (`git add . && git commit -m "popis" && git push`)
V chatu pošleš raw URL souboru nebo celé složky
Claude čte aktuální verzi a pracuje s ní
---
Stav projektu (červen 2026)
[x] Funkce pro čištění a normalizaci kontaktů (`fn_*`, `usp_ExtractContacts`)
[x] OR import script funkční, Z_ORstagg naplněna
[x] Referenční data připravena (Staty, Formy, Jmena, Prijmeni, Tituly) – čeká na import
[ ] `cfg_Staty` – doplnit IsEU, IsEURzone, DicPrefix, PSCFormat, pak import
[ ] `cfg_Formy` – import
[ ] `fn_NormalizeICO` + `fn_NormalizeDIC`
[ ] `fn_NormalizeDate`
[ ] `fn_ParseTitle` – extrakce titulů, RC, datumů z FO_TitulPred/Za
[ ] `fn_NormalizeName` – Title Case + lookup
[ ] STK import script
[ ] Registr vozidel import script
