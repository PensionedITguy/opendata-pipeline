Specifikace transformační vrstvy – opendata pipeline
Verze: 1.0 | Datum: červen 2026 | Autor: Rudolf / Claude
---
1. Kontext a filosofie
Zdroje dat
Z_ORstagg – Obchodní rejstřík (OR), ~500 XML souborů, tabulky `src_OR_Entity` + `src_OR_Udaje`
Z_RAstagg – Registr vozidel (RA), 2 CSV soubory (~16 GB vozidla, ~6 GB majitelé)
Z_STKstagg – STK a emise, ~6 000 XML souborů (již máme naimportován stagging)
Z_DIVstagg – různé menší datasety
Vrstvení
```
src_*  (staging, surový import, žádná logika)
  ↓
stg_*  (čištění, standardizace, validace)
  ↓
dim_* / fact_*  (produkční tabulky, budoucí fáze)
```
Principy
Staging se nemění – transformace probíhá vždy nad `src_` do `stg_`
Co nejde rozpoznat (cizí jméno, zahraniční PSČ), uložíme jak je
Cenná data na nesprávném místě (RC v titulu, datum v titulu) → zachránit, ne zahodit
Osobní citlivá data (RC) → nikdy plain text, pouze hash
Pozor, bez ohledu na níže navržené dimenze sloupců je nutné zachovávat jejich shodu ve všech tabulkách. 
Nahraji sem soubor StandardTabulek.xlsx, kde jsou již některé často používané sloupce sjednocené.
Jinak si zbytečně budeme vytvářet problém při konsolidaci dat z různých tabulek.
---
2. Referenční tabulky (databáze `opendata`)
2.1 src_Jmena
Zdroj: ČSÚ, nejčetněji používaná jména do počtu 10 v ČR.
Sloupec	Typ	Popis
ID	int	PK
R_Jmeno	varchar(30)	Jméno (správná diakritika, Title Case)
R_Sex	varchar(1)	M / F / NULL (cizí jména bez určeného pohlaví)
R_Cetnost	tinyint	2=české ČSÚ, 1=méně časté, 0=cizí bez pohlaví
R_Rank	smallint	Pořadí četnosti
Použití: lookup při normalizaci jména → správná diakritika + pohlaví.
Pokud jméno v tabulce není → cizinec, uložit po Title Case přepisu, pohlaví NULL.
2.2 src_Prijmeni
Zdroj: ČSÚ, příjmení s četností min. 10 v ČR.
Sloupec	Typ	Popis
ID	int	PK
R_Prijmeni	varchar(30)	Příjmení
R_Sex	varchar(1)	M / F
R_Rank	smallint	Pořadí
R_Pocet	int	Absolutní počet v ČR
R_Cetnost	tinyint	Kategorie četnosti
R_OkresNazev	varchar(35)	Okres s nejvyšší koncentrací
R_OkresID	int	
R_OkresRUIAN	int	RUIAN kód okresu
2.3 cfg_Tituly_Pred (k vytvoření)
Zdroj: `TitulPred.xlsx` – 101 platných titulů před jménem. (některým chybí na konci tečka, doplnit)
Sloupec	Typ	Popis
TitulID	int	PK IDENTITY
TitZkr	nvarchar(30)	Oficiální zkratka (normalizovaný tvar)
TitNazev	nvarchar(200)	Plný název
DatZmeny	date	Datum platnosti
Použití: po tokenizaci TitulPred → každý token lookupovat, nerozpoznané = profese/nesmysl.
2.4 cfg_Tituly_Za (k vytvoření)
Zdroj: `TitulZa.xlsx` – 13 platných titulů za jménem.
Sloupec	Typ	Popis
TitulZaID	int	PK IDENTITY
TitulZa	nvarchar(30)	Titul (normalizovaný tvar)
Tituly za jménem jsou odděleny čárkou. Pořadí dle zákona.
2.5 cfg_AdrMista (máme vytvořenou)
Zdroj: ČÚZK, ~3 mil. záznamů, 1 GB.
Sloupec	Typ	Popis
AdmID	int	PK – unikátní ID adresního místa
KodObce	int	RUIAN kód obce
NazevObce	nvarchar(100)	
KodCastiObce	int	NULL pro jednoduché obce
NazevCastiObce	nvarchar(100)	
KodUlice	int	
NazevUlice	nvarchar(100)	
TypCisla	varchar(10)	`č.p.` / `č.e.` / bez čp.
CisloPopisne	varchar(10)	
CisloOrientacni	varchar(10)	
CisloOrientacniPismeno	varchar(2)	
PSC	char(5)	
SouradniceY	decimal(12,2)	S-JTSK
SouradniceX	decimal(12,2)	S-JTSK
DatumPlatnosti	date	
Použití: lookup obec + ulice + čp. → AdmID → PSČ + souřadnice. Kde nenajdeme, AdmID = NULL.
2.6 cfg_Staty (k vytvoření)
Zdroj: `Staty_v2.xlsx`.
Klíčové sloupce: ISOa2, ISOa3, ZemeNazev, TelPrefix (varchar s `+`),
IsEU (bit), IsEURzone (bit), DicPrefix (varchar(3)), PSCFormat (varchar(50)).
2.7 cfg_Formy (k vytvoření)
Zdroj: `cFormy.csv` – 90 právních forem vč. historických.
Klíčový sloupec: `rFormaKod` (zkratka z názvu XML souboru, např. `sro`, `as`, `os`).
---
3. Hotové funkce (databáze `opendata`)
Funkce	Popis	Stav
`fn_CleanString`	Technické čištění (control chars, BOM, mezery)	✅
`fn_CleanStringExt`	+ Unicode normalizace (pomlčky, uvozovky)	✅
`fn_SplitContacts`	Rozdělení vícehodnotového pole na tokeny	✅
`fn_NormalizeEmail`	RFC 5321, validace TLD	✅
`fn_NormalizePhone`	E.164, parametr defaultCC	✅
`fn_NormalizeUrl`	https://, trailing /, markdown	✅
`fn_NormalizeICO`	8 číslic s nulami, volitelný checksum mod 11	✅
`usp_ExtractContacts`	Orchestrace kontaktů do stg_kontakty	✅
---
4. Funkce k implementaci
4.1 fn_NormalizeDIC
Vstup: raw DIČ string, kód státu (ISOa2 z cfg_Staty)
Logika:
Vyčistit (fn_CleanString), odstranit mezery/pomlčky
Pokud začíná prefixem státu (lookup v cfg_Staty.DicPrefix) → zachovat
Pokud začíná číslicí a stát=CZ → doplnit prefix `CZ`
Ověřit že za prefixem jsou jen číslice (pro CZ: 8–10 číslic)
CZ DIČ = `CZ` + IČO → pro fyzické osoby `CZ` + RČ (10 číslic)
Vrátit normalizované DIČ nebo NULL
Závislosti: `cfg_Staty` (DicPrefix), `fn_NormalizeICO`
4.2 fn_NormalizeDate
Vstup: raw datumový string
Podporované formáty:
`D.M.YYYY`, `DD.MM.YYYY`, `D. M. YYYY` (české)
`YYYY-MM-DD` (ISO)
`DD/MM/YYYY`, `MM/DD/YYYY`
Rok samotný: `1965` → `1965-01-01` (příznak neurčitosti)
Vrátí: `date` nebo NULL pokud nerozpoznatelné.
Pozor: `30.40.1967` (viděli jsme v datech) → NULL, neplatný datum.
4.3 fn_ParseTitle
Vstup: `@TitulPred nvarchar(50)`, `@TitulZa nvarchar(500)`, `@DatNar date`
Výstup: tabulka (TABLE) nebo více výstupních parametrů:
```
TitulPredNorm   nvarchar(200)  -- normalizované tituly před, oddělené mezerou
TitulZaNorm     nvarchar(200)  -- normalizované tituly za, oddělené čárkou
FO_DatNar_New   date           -- datum pokud extrahováno z titulu
RC_Hash         varbinary(32)  -- SHA2_256 hash RC pokud nalezeno
Profese         nvarchar(200)  -- povolání/generační označení (zachovat)
```
Logika TitulPred:
Odstraň pořadové číslo na začátku: `1.`, `1)`, `2.`, `2)`, `10.` atd.
Tokenizuj (oddělovače: mezera, čárka, středník)
Každý token lookupuj v `cfg_Tituly_Pred.TitZkr` (case-insensitive)
Rozpoznaný → přidej normalizovaný tvar do `TitulPredNorm`
Nerozpoznaný → ignoruj (profese, nesmysl)
Speciální: RC formát (`NNNNNN/NNNN`) → hashuj do `RC_Hash`
Speciální: datum formát → `fn_NormalizeDate` → `FO_DatNar_New`
Logika TitulZa:
Tokenizuj podle čárky a středníku
Každý token trimuj a lookupuj v `cfg_Tituly_Za.TitulZa` (case-insensitive)
Rozpoznaný titul → přidej do `TitulZaNorm`
RC formát → `RC_Hash`
Datum formát → `fn_NormalizeDate` → `FO_DatNar_New`
Samotná `.` nebo `-` → ignoruj
Zbytek (povolání, generační) → `Profese`
Pravidla pro výstup titulů (dle zákona):
Tituly před jménem: odděleny mezerou, bez et
Tituly za jménem: za příjmením čárka, tituly odděleny čárkou
Příklad: `Ing. Mgr. Jan Novák, Ph.D., MBA`
4.4 fn_NormalizeName
Vstup: `@Jmeno nvarchar(200)`, `@Prijmeni nvarchar(500)`, `@StatKod varchar(5)`
Výstup: `@JmenoNorm`, `@PrijmeniNorm`, `@Sex char(1)`
Logika jméno:
`fn_CleanStringExt` → základní čištění
Lookup v `src_Jmena` (case-insensitive): pokud nalezeno → vrátit `R_Jmeno` (správná diakritika) + `R_Sex`
Pokud nenalezeno → Title Case přepis, Sex = NULL (cizinec)
Logika příjmení:
`fn_CleanStringExt`
Lookup v `src_Prijmeni`: pokud nalezeno → vrátit `R_Prijmeni` + `R_Sex`
Pokud nenalezeno → Title Case přepis, Sex = NULL
Složená příjmení (mezera nebo pomlčka): každá část samostatně
Title Case pro češtinu:
První písmeno každého slova na velké, zbytek malé
Výjimka: `von`, `van`, `de`, `bin`, `al` → malé (šlechtické/arabské partikule)
Pozor na UPPERCASE vstup z OR: `PODHRÁZSKÁ` → lookup → `Podhrázská`
4.5 fn_NormalizePSC (jednoduchá)
Vstup: raw PSČ, `@StatKod varchar(5)`
Logika:
Pokud stát = CZ: musí být 5 číslic → doplnit vedoucí nulu pokud 4 číslice → jinak NULL
Ostatní státy: `fn_CleanString` + trim → vrátit jak je (zahraniční formáty jsou legitimní)
4.6 fn_LookupAdmID (procedura nebo funkce)
Vstup: `@Obec`, `@Ulice`, `@CisloPopisne`, `@CisloOrientacni`
Logika:
Přesná shoda: obec + ulice + čp. + čo.
Přesná shoda: obec + ulice + čp. (bez čo.)
Fuzzy: obec + čp. (bez ulice – malé obce)
Pokud nic → NULL
Výstup: `AdmID int` nebo NULL
---
5. Rozšíření staging tabulek
5.1 Z_ORstagg.dbo.src_OR_Udaje – přidat sloupce
```sql
ALTER TABLE Z_ORstagg.dbo.src_OR_Udaje ADD
    FO_Profese    NVARCHAR(200)  NULL,  -- povolání/generační z TitulZa
    FO_RC_Hash    VARBINARY(32)  NULL,  -- SHA2_256 hash rodného čísla
    AdmID         INT            NULL;  -- ČÚZK adresní místo
```
RC ukládáme výhradně jako hash (GDPR) – nikdy plain text.
5.2 Tabulka log_ExtractedData (databáze opendata)
Pro záchranný log – data nalezená na nesprávném místě:
```sql
CREATE TABLE opendata.dbo.log_ExtractedData (
    ID          INT IDENTITY(1,1) NOT NULL,
    Zdroj       VARCHAR(20)   NOT NULL,   -- 'OR', 'RA', 'STK'
    ZdrojTab    VARCHAR(100)  NOT NULL,   -- 'Z_ORstagg.dbo.src_OR_Udaje'
    ZdrojID     INT           NOT NULL,   -- UdajID / primární klíč zdrojového řádku
    ICO         VARCHAR(8)    NULL,       -- IČO entity
    TypNalezu   VARCHAR(30)   NOT NULL,   -- 'RC', 'DAT_NAR', 'ADRESA', 'SPZ'
    ZdrojSloup  VARCHAR(50)   NOT NULL,   -- 'FO_TitulPred', 'Poznamka'
    HodnotaRaw  NVARCHAR(500) NOT NULL,   -- původní hodnota
    HodnotaNorm NVARCHAR(200) NULL,       -- normalizovaná hodnota
    DatZprac    DATETIME      NOT NULL CONSTRAINT DF_ExtractedData_Dat DEFAULT GETDATE(),
    CONSTRAINT PK_log_ExtractedData PRIMARY KEY CLUSTERED (ID)
)
```
---
6. Validace IČO – pravidla
Situace	Parametr	Chování
Import z OR, ARES, RA	`@ValidateChecksum=0` (výchozí)	Jen normalizace na 8 číslic
Ruční vstup, formulář	`@ValidateChecksum=1`	Plná validace mod 11
Historická IČO (před ~1990)	`@ValidateChecksum=0`	Mod 11 na ně neplatí
Délka > 8 číslic	–	Vždy NULL (chyba zdroje)
Příklady chybných IČO z RA: `1001427670` (10 číslic) – přebývající číslice za IČO, chyba exportu.
---
7. PSČ – pravidla normalizace
Stát	Pravidlo	Příklad
CZ	Musí být 5 číslic, doplnit vedoucí 0	`5101` → `05101`
PL	Formát `XX-XXX`, 5 znaků s pomlčkou	`43-30` → zachovat
AT	4 číslice	`1010` → zachovat
NL	Alfanumerické 6 znaků	`1077XA` → zachovat
GB	Alfanumerické	`N22 8H` → zachovat
Ostatní	Uložit jak je po fn_CleanString	–
---
8. Tituly – pravidla standardizace
Zdroj standardu
Tituly před jménem: 101 titulů v `cfg_Tituly_Pred` (zákon č. 111/1998 Sb. + mezinárodní)
Tituly za jménem: 13 titulů v `cfg_Tituly_Za`
Pravidla zápisu (dle zákona)
Tituly před jménem: odděleny mezerou, seřazeny od nejvyššího: `prof. Ing. Jan Novák`
Tituly za jménem: za příjmením čárka, tituly odděleny čárkou: `Jan Novák, Ph.D., MBA`
Nepoužívá se `et` mezi tituly
Uvádí se jen nejvyšší titul stejné skupiny (ne `Ing. et Bc.`)
Co se při parsování zachytí navíc
Hodnota v titulním poli	Akce
`.`, `-`, `–` samotné	Zahodit (NULL)
Datum `D.M.YYYY`	→ `FO_Narozeni` (pokud NULL) nebo log konfliktu
RC `NNNNNN/NNNN`	→ `FO_RC_Hash` (SHA2_256) + `log_ExtractedData`
Povolání (`zemědělec`, `újezdní tajemník`)	→ `FO_Profese`
Generační (`ml.`, `st.`)	→ `FO_Profese`
Kombinace titulů za čárkou (`Ph.D., LL.M.`)	→ tokenizovat, každý lookup
---
9. Adresní místa (AdmID)
ČÚZK vydává dataset adresních míst (~3 mil. záznamů, 1 GB).
Každé adresní místo = jeden konkrétní dům (nebo vchod) s unikátním ID.
Z AdmID lze odvodit: PSČ, souřadnice S-JTSK, okres, kraj, kód obce, název ulice.
Lookup strategie (fn_LookupAdmID)
Přesná shoda: obec + ulice + čp. + čo.
Přesná shoda: obec + ulice + čp.
Bez ulice: obec + čp. (malé obce bez pojmenovaných ulic)
NULL pokud nenalezeno
Kde přidat AdmID
`src_OR_Udaje.AdmID` – adresa osoby (sídlo, bydliště)
`stg_` vrstvy kde jsou adresy
Případně `rv_vlastnici` v Z_RAstagg
---
10. Implementační pořadí
Pořadí	Krok	Závislosti
1	`cfg_Tituly_Pred` + `cfg_Tituly_Za` – DDL + import	xlsx soubory
2	`cfg_Formy` – DDL + import	cFormy.csv
3	`cfg_Staty` – DDL + import (po doplnění IsEU, DicPrefix...)	xlsx + ruční doplnění
4	`cfg_AdrMista` – DDL + import ČÚZK	1 GB dataset
5	`log_ExtractedData` – CREATE TABLE	–
6	ALTER `src_OR_Udaje` (FO_Profese, FO_RC_Hash, AdmID)	–
7	`fn_NormalizeDIC`	cfg_Staty
8	`fn_NormalizeDate`	–
9	`fn_ParseTitle`	cfg_Tituly_Pred, cfg_Tituly_Za, fn_NormalizeDate
10	`fn_NormalizePSC`	cfg_Staty
11	`fn_NormalizeName`	src_Jmena, src_Prijmeni
12	`fn_LookupAdmID`	cfg_AdrMista
13	Transformační procedury `stg_*`	vše výše
---
11. Stav repo (červen 2026)
```
db/opendata/
├── functions/
│   ├── fn_CleanString.sql        ✅
│   ├── fn_CleanStringExt.sql     ✅
│   ├── fn_SplitContacts.sql      ✅
│   ├── fn_NormalizeEmail.sql     ✅
│   ├── fn_NormalizePhone.sql     ✅
│   ├── fn_NormalizeUrl.sql       ✅
│   └── fn_NormalizeICO.sql       ✅
├── procedures/
│   └── usp_ExtractContacts.sql   ✅
├── tables/
│   ├── src_Jmena.sql             ✅
│   └── src_Prijmeni.sql          ✅
└── python/
    ├── import_or.py              ✅
    └── analyze.py                ✅

db/Z_ORstagg/
├── tables/
│   ├── src_OR_Entity.sql         ✅
│   └── src_OR_Udaje.sql          ✅
└── scripts/
    └── import_or.py              ✅

docs/
└── transformace.md               ✅ (tento dokument)
```
