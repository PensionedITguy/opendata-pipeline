USE [Opendata]
GO

/****** Object:  UserDefinedFunction [dbo].[fn_NormalizeUrl]    Script Date: 05.06.2026 19:54:34 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO



-- ============================================================
-- fn_NormalizeUrl
-- Normalizuje URL adresu
--
-- Parametry:
--   @input      - vstupní řetězec
--   @importAsIs - 1 = jen fn_CleanString + lowercase, bez normalizace
--                 0 = plná normalizace + validace (výchozí)
--
-- Vrací:
--   Normalizovanou URL (lowercase, https://, bez trailing /)
--   NULL pokud:
--     • vstup je prázdný/NULL
--     • schéma není http:// nebo https:// (po doplnění)
--     • doména neobsahuje tečku
--     • TLD kratší než 2 znaky nebo obsahuje nealfabetické znaky
--     • URL obsahuje mezery (po vyčištění)
--
-- Normalizace:
--   • Markdown [text](url)        → extrahovat jen URL
--   • začíná www. nebo bez schématu → doplnit https://
--   • http://                     → zachovat (může být záměrné)
--   • trailing /                  → odstranit
--   • ftp:// a jiná schémata      → NULL
--
-- Poznámka:
--   Funkce neověřuje existenci/dostupnost webu
--   Parametr @importAsIs připraven na budoucí cfg_NormRules
-- ============================================================
CREATE   FUNCTION [dbo].[fn_NormalizeUrl]
(
    @input      NVARCHAR(500),
    @importAsIs BIT = 0
)
RETURNS NVARCHAR(500)
AS
BEGIN
    IF @input IS NULL RETURN NULL;

    -- Krok 1: technické čištění + lowercase
    DECLARE @clean NVARCHAR(500) = LOWER([dbo].[fn_CleanString](@input));
    IF @clean IS NULL RETURN NULL;

    -- ImportAsIs: vrátit vyčištěný lowercase string bez normalizace
    IF @importAsIs = 1 RETURN @clean;

    -- Krok 2: Extrahovat URL z markdown formátu [text](url)
    -- Vzor: [cokoliv](url) → url
    DECLARE @md_start INT = CHARINDEX(N'](', @clean);
    IF @md_start > 0
    BEGIN
        DECLARE @url_start INT = @md_start + 2;
        DECLARE @url_end   INT = CHARINDEX(N')', @clean, @url_start);
        IF @url_end > @url_start
            SET @clean = SUBSTRING(@clean, @url_start, @url_end - @url_start);
        ELSE
            SET @clean = SUBSTRING(@clean, @url_start, LEN(@clean));
    END

    -- Trim po extrakci
    SET @clean = LTRIM(RTRIM(@clean));
    IF LEN(@clean) = 0 RETURN NULL;

    -- Krok 3: Nesmí obsahovat mezery
    IF CHARINDEX(N' ', @clean) > 0 RETURN NULL;

    -- Krok 4: Normalizace schématu
    IF LEFT(@clean, 8)  = N'https://'
        SET @clean = @clean;  -- ok
    ELSE IF LEFT(@clean, 7) = N'http://'
        SET @clean = @clean;  -- ok, zachovat
    ELSE IF LEFT(@clean, 4) = N'www.'
        SET @clean = N'https://' + @clean;
    ELSE IF CHARINDEX(N'://', @clean) > 0
        -- Jiné schéma (ftp://, mailto:// atd.) → NULL
        RETURN NULL;
    ELSE
        -- Bez schématu, bez www → doplnit https://
        SET @clean = N'https://' + @clean;

    -- Krok 5: Extrahovat doménu (část mezi :// a prvním / nebo koncem)
    DECLARE @domain_start INT = CHARINDEX(N'://', @clean) + 3;
    DECLARE @domain_end   INT = CHARINDEX(N'/', @clean, @domain_start);
    DECLARE @domain NVARCHAR(200);

    IF @domain_end > 0
        SET @domain = SUBSTRING(@clean, @domain_start, @domain_end - @domain_start);
    ELSE
        SET @domain = SUBSTRING(@clean, @domain_start, LEN(@clean));

    -- Odstranit port pokud je přítomen (domain:8080 → domain)
    DECLARE @port_pos INT = CHARINDEX(N':', @domain);
    IF @port_pos > 0
        SET @domain = LEFT(@domain, @port_pos - 1);

    IF LEN(@domain) = 0 RETURN NULL;

    -- Krok 6: Validace domény
    -- Nesmí začínat nebo končit tečkou
    IF LEFT(@domain, 1)  = N'.' RETURN NULL;
    IF RIGHT(@domain, 1) = N'.' RETURN NULL;

    -- Musí obsahovat alespoň jednu tečku
    IF CHARINDEX(N'.', @domain) = 0 RETURN NULL;

    -- TLD validace
    DECLARE @last_dot INT =
        LEN(@domain) - CHARINDEX(N'.', REVERSE(@domain)) + 1;
    DECLARE @tld NVARCHAR(20) =
        SUBSTRING(@domain, @last_dot + 1, LEN(@domain));
    IF LEN(@tld) < 2 RETURN NULL;
    IF @tld LIKE N'%[^a-z]%' COLLATE Latin1_General_CI_AS RETURN NULL;

    -- Krok 7: Odstranit trailing / na konci celé URL
    WHILE RIGHT(@clean, 1) = N'/'
        SET @clean = LEFT(@clean, LEN(@clean) - 1);

    RETURN @clean;
END
GO


