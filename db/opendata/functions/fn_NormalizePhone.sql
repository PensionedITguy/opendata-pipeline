USE [Opendata]
GO

/****** Object:  UserDefinedFunction [dbo].[fn_NormalizePhone]    Script Date: 05.06.2026 19:54:17 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO



-- ============================================================
-- fn_NormalizePhone
-- Normalizuje jedno telefonní číslo do formátu E.164
--
-- Parametry:
--   @input      - jeden token (výstup fn_SplitContacts)
--   @defaultCC  - výchozí předvolba BEZ + a BEZ nul, např. '420'
--                 NULL = nepřidávat předvolbu pokud chybí
--   @importAsIs - 1 = jen fn_CleanString, bez normalizace
--                 0 = plná normalizace (výchozí)
--
-- Vrací:
--   E.164 formát: +420603111111
--   NULL pokud:
--     • vstup je prázdný/NULL
--     • číslo nevyhoví validaci délky
--     • chybí předvolba a @defaultCC je NULL
--     • @importAsIs = 1 → vrací vyčištěný raw string (ne NULL)
--
-- Validace délky (počet číslic včetně předvolby):
--   Minimálně 7 číslic, maximálně 15 číslic (ITU-T E.164 max)
--
-- Poznámka k rozšíření:
--   Parametry jsou připraveny na budoucí tabulku pravidel
--   cfg_NormRules - orchestrace předá @defaultCC a @importAsIs
--   podle pravidel pro daný zdroj/zemi, funkce zůstane beze změny
-- ============================================================
CREATE   FUNCTION [dbo].[fn_NormalizePhone]
(
    @input      NVARCHAR(100),
    @defaultCC  VARCHAR(5) = NULL,
    @importAsIs BIT        = 0
)
RETURNS NVARCHAR(20)
AS
BEGIN
    IF @input IS NULL RETURN NULL;

    -- Krok 1: technické čištění
    DECLARE @clean NVARCHAR(100) = [dbo].[fn_CleanString](@input);
    IF @clean IS NULL RETURN NULL;

    -- ImportAsIs: vrátit vyčištěný string bez normalizace
    IF @importAsIs = 1 RETURN @clean;

    -- Krok 2: Odstranit formátovací znaky
    -- závorky, pomlčky, tečky, lomítka, mezery
    DECLARE @stripped NVARCHAR(100) = @clean;
    SET @stripped = REPLACE(@stripped, N'(',  N'');
    SET @stripped = REPLACE(@stripped, N')',  N'');
    SET @stripped = REPLACE(@stripped, N'-',  N'');
    SET @stripped = REPLACE(@stripped, N'.',  N'');
    SET @stripped = REPLACE(@stripped, N'/',  N'');
    SET @stripped = REPLACE(@stripped, N' ',  N'');

    IF LEN(@stripped) = 0 RETURN NULL;

    -- Krok 3: Normalizace předvolby
    DECLARE @normalized NVARCHAR(20);

    IF LEFT(@stripped, 1) = N'+'
    BEGIN
        -- Má explicitní + → zachovat jak je
        SET @normalized = @stripped;
    END
    ELSE IF LEFT(@stripped, 2) = N'00'
    BEGIN
        -- 00XX → +XX
        SET @normalized = N'+' + SUBSTRING(@stripped, 3, LEN(@stripped));
    END
    ELSE
    BEGIN
        -- Nemá předvolbu
        IF @defaultCC IS NOT NULL
            SET @normalized = N'+' + @defaultCC + @stripped;
        ELSE
            RETURN NULL;  -- nehádat předvolbu
    END

    -- Krok 4: Ověřit že za + jsou jen číslice
    DECLARE @digits NVARCHAR(20) = SUBSTRING(@normalized, 2, LEN(@normalized));
    IF @digits LIKE N'%[^0-9]%' RETURN NULL;

    -- Krok 5: Validace délky
    -- Celkový počet číslic (bez +): min 7, max 15 (E.164)
    DECLARE @digit_count INT = LEN(@digits);
    IF @digit_count < 7  RETURN NULL;
    IF @digit_count > 15 RETURN NULL;

    RETURN @normalized;
END

GO


