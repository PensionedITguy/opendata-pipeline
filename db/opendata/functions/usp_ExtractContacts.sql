USE [Opendata]
GO

/****** Object:  StoredProcedure [dbo].[usp_ExtractContacts]    Script Date: 05.06.2026 19:55:08 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO



-- ============================================================
-- usp_ExtractContacts
-- Orchestrační procedura - extrahuje kontaktní údaje
-- z libovolné zdrojové tabulky do stg_kontakty
--
-- Parametry:
--   @ZdrojTab        - třídílný název zdrojové tabulky
--                      např. 'opendata.dbo.dim_DomainCZ'
--   @ZdrojIDSloupec  - název sloupce s vazebním klíčem
--                      např. 'D_Nazev', 'F_ICO', 'PCV'
--   @SloupecNazev    - název sloupce s kontaktními daty
--                      např. 'D_Tel', 'D_Email', 'D_Web'
--   @TypKontaktu     - 1=telefon, 2=email, 3=url
--   @Zdroj           - označení zdroje ('OR', 'RSV', 'Pohoda'...)
--   @DefaultCC       - výchozí předvolba pro telefony (např. '420')
--                      NULL = nepřidávat
--   @ImportAsIs      - 0=normalizovat (výchozí), 1=jen vyčistit
--   @Prepsat         - 1=smazat existující záznamy pro ZdrojTab+SloupecNazev
--                      0=přeskočit pokud již existují (výchozí)
-- ============================================================
CREATE   PROCEDURE [dbo].[usp_ExtractContacts]
    @ZdrojTab       varchar(100),
    @ZdrojIDSloupec varchar(50),
    @SloupecNazev   varchar(50),
    @TypKontaktu    tinyint,
    @Zdroj          varchar(20)  = NULL,
    @DefaultCC      varchar(5)   = NULL,
    @ImportAsIs     bit          = 0,
    @Prepsat        bit          = 0
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @t0         datetime = GETDATE();
    DECLARE @dnes       date     = CAST(GETDATE() AS date);
    DECLARE @sql        nvarchar(max);
    DECLARE @delimiters varchar(5);
    DECLARE @pocet_src  int = 0;
    DECLARE @pocet_ok   int = 0;
    DECLARE @pocet_null int = 0;
    DECLARE @pocet_skip int = 0;
    DECLARE @msg        varchar(200);

    -- Oddělovače podle typu
    SET @delimiters = CASE @TypKontaktu
        WHEN 1 THEN ';,'   -- telefon: středník i čárka
        WHEN 2 THEN ';'    -- email: středník
        WHEN 3 THEN ';'    -- url: středník
        ELSE ';'
    END;

    RAISERROR('usp_ExtractContacts: %s / %s [Typ=%d]',
        0, 1, @ZdrojTab, @SloupecNazev, @TypKontaktu) WITH NOWAIT;

    -- Přepsat: smazat existující záznamy pro tento zdroj+sloupec
    IF @Prepsat = 1
    BEGIN
        DELETE FROM opendata.dbo.stg_kontakty
        WHERE ZdrojTab     = @ZdrojTab
          AND SloupecNazev = @SloupecNazev;

        SET @msg = '  Smazáno existujících: ' + CAST(@@ROWCOUNT AS varchar);
        RAISERROR(@msg, 0, 1) WITH NOWAIT;
    END
    ELSE
    BEGIN
        -- Zkontrolovat jestli už záznamy existují
        IF EXISTS (
            SELECT 1 FROM opendata.dbo.stg_kontakty
            WHERE ZdrojTab     = @ZdrojTab
              AND SloupecNazev = @SloupecNazev
        )
        BEGIN
            RAISERROR('  Záznamy již existují, @Prepsat=0 - přeskočeno.', 0, 1) WITH NOWAIT;
            RETURN;
        END
    END

    -- Načíst zdrojová data do temp tabulky
    CREATE TABLE #src (
        ZdrojID     varchar(50),
        HodnotaRaw  varchar(500)
    );

    SET @sql = N'
        INSERT INTO #src (ZdrojID, HodnotaRaw)
        SELECT
            CAST(' + QUOTENAME(@ZdrojIDSloupec) + N' AS varchar(50)),
            CAST(' + QUOTENAME(@SloupecNazev)   + N' AS varchar(500))
        FROM ' + @ZdrojTab + N'
        WHERE ' + QUOTENAME(@SloupecNazev) + N' IS NOT NULL
          AND LEN(LTRIM(RTRIM(CAST(' + QUOTENAME(@SloupecNazev) + N' AS varchar(500))))) > 0';

    EXEC sp_executesql @sql;

    SET @pocet_src = @@ROWCOUNT;
    SET @msg = '  Načteno zdrojových záznamů: ' + CAST(@pocet_src AS varchar);
    RAISERROR(@msg, 0, 1) WITH NOWAIT;

    IF @pocet_src = 0
    BEGIN
        DROP TABLE #src;
        RAISERROR('  Žádná data ke zpracování.', 0, 1) WITH NOWAIT;
        RETURN;
    END

    -- Zpracovat každý záznam + split + normalizace
    INSERT INTO opendata.dbo.stg_kontakty
        (ZdrojTab, ZdrojID, SloupecNazev, TypKontaktu, Poradi,
         Hodnota, HodnotaRaw, DatImport, Zdroj)
    SELECT
        @ZdrojTab,
        s.ZdrojID,
        @SloupecNazev,
        @TypKontaktu,
        sc.Poradi,
        -- Normalizace podle typu
        CASE @TypKontaktu
            WHEN 1 THEN opendata.dbo.fn_NormalizePhone(sc.Hodnota, @DefaultCC, @ImportAsIs)
            WHEN 2 THEN opendata.dbo.fn_NormalizeEmail(sc.Hodnota, @ImportAsIs)
            WHEN 3 THEN opendata.dbo.fn_NormalizeUrl(sc.Hodnota, @ImportAsIs)
            ELSE        opendata.dbo.fn_CleanString(sc.Hodnota)
        END,
        sc.Hodnota,   -- HodnotaRaw = token před normalizací
        @dnes,
        @Zdroj
    FROM #src s
    CROSS APPLY opendata.dbo.fn_SplitContacts(
        opendata.dbo.fn_CleanString(s.HodnotaRaw), @delimiters) sc;

    DECLARE @pocet_ins int = @@ROWCOUNT;

    -- Statistiky
    SELECT
        @pocet_ok   = COUNT(*) FROM opendata.dbo.stg_kontakty
        WHERE ZdrojTab = @ZdrojTab AND SloupecNazev = @SloupecNazev
          AND DatImport = @dnes AND Hodnota IS NOT NULL;

    SELECT
        @pocet_null = COUNT(*) FROM opendata.dbo.stg_kontakty
        WHERE ZdrojTab = @ZdrojTab AND SloupecNazev = @SloupecNazev
          AND DatImport = @dnes AND Hodnota IS NULL;

    DROP TABLE #src;

    -- Výpis výsledku
    RAISERROR('  Vloženo celkem  : %d', 0, 1, @pocet_ins)  WITH NOWAIT;
    RAISERROR('  Normalizováno OK: %d', 0, 1, @pocet_ok)   WITH NOWAIT;
    RAISERROR('  Nelze norm. NULL: %d', 0, 1, @pocet_null) WITH NOWAIT;
    DECLARE @ms int = DATEDIFF(ms, @t0, GETDATE());
    RAISERROR('  Čas: %d ms', 0, 1, @ms) WITH NOWAIT;
END

GO


