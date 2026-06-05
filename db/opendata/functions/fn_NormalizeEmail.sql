USE [Opendata]
GO

/****** Object:  UserDefinedFunction [dbo].[fn_NormalizeEmail]    Script Date: 05.06.2026 19:54:03 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO



-- ============================================================
-- fn_NormalizeEmail  (v2)
-- Normalizuje jeden emailový řetězec dle RFC 5321 / RFC 5322
--
-- Parametry:
--   @input      - jeden token (výstup fn_SplitContacts)
--   @importAsIs - 1 = jen fn_CleanString + lowercase, bez validace
--                 0 = plná normalizace + validace (výchozí)
--
-- Vrací:
--   Normalizovaný email (lowercase, trimovaný, RFC čištění)
--   NULL pokud:
--     • vstup je prázdný/NULL
--     • neobsahuje právě jedno @
--     • local část je po čištění prázdná
--     • local část obsahuje dvě tečky za sebou (..)
--     • domain část neobsahuje tečku / začíná nebo končí tečkou
--     • TLD kratší než 2 znaky nebo obsahuje nečíselné znaky
--
-- RFC 5321 local část:
--   Povolené znaky: a-z 0-9 ! # $ % & ' * + - / = ? ^ _ ` { | } ~ .
--   Tečka: nesmí být první, poslední ani zdvojená
--   Znaky mimo tuto množinu na začátku jsou ořezány
--
-- Poznámka:
--   Funkce nefiltruje placeholder emaily (info@, admin@ atd.)
--   Parametr @importAsIs připraven na budoucí cfg_NormRules
-- ============================================================
CREATE   FUNCTION [dbo].[fn_NormalizeEmail]
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

    -- ImportAsIs: vrátit vyčištěný lowercase string bez validace
    IF @importAsIs = 1 RETURN @clean;

    -- Krok 2: Ověřit právě jedno @
    DECLARE @at_count INT =
        LEN(@clean) - LEN(REPLACE(@clean, N'@', N''));
    IF @at_count <> 1 RETURN NULL;

    -- Krok 3: Rozdělit na local a domain části
    DECLARE @at_pos INT = CHARINDEX(N'@', @clean);
    DECLARE @local  NVARCHAR(200) = LEFT(@clean, @at_pos - 1);
    DECLARE @domain NVARCHAR(300) = SUBSTRING(@clean, @at_pos + 1, LEN(@clean));

    -- Krok 4: Čištění local části
    -- Ořezat úvodní znaky které nejsou v RFC 5321 množině
    -- Povolené: a-z 0-9 ! # $ % & ' * + - / = ? ^ _ ` { | } ~ .
    -- Nepovolené na začátku jsou ořezány dokud nenarazíme na platný znak
    WHILE LEN(@local) > 0
    BEGIN
        DECLARE @first NCHAR(1) = LEFT(@local, 1);

        -- Tečka na začátku → ořezat vždy (RFC zakazuje)
        IF @first = N'.' BEGIN SET @local = SUBSTRING(@local, 2, LEN(@local)); CONTINUE; END

        -- Povolené RFC znaky na začátku: písmena, číslice a vybrané speciální
        -- Používáme explicitní testy místo LIKE (+ a _ mají v LIKE speciální význam)
        IF @first LIKE N'[a-z]' COLLATE Latin1_General_CI_AS BREAK;
        IF @first LIKE N'[0-9]' COLLATE Latin1_General_CI_AS BREAK;
        -- Povolené speciální znaky dle RFC 5321 které smí být na začátku
        IF @first IN (N'!', N'#', N'$', N'%', N'&', N'''', N'*',
                      N'+', N'-', N'/', N'=', N'?', N'^', N'_',
                      N'`', N'{', N'|', N'}', N'~') BREAK;

        -- Cokoliv jiného → ořezat
        SET @local = SUBSTRING(@local, 2, LEN(@local));
    END

    -- Ořezat tečky na konci local části
    WHILE LEN(@local) > 0 AND RIGHT(@local, 1) = N'.'
        SET @local = LEFT(@local, LEN(@local) - 1);

    -- Local část nesmí být prázdná
    IF LEN(@local) = 0 RETURN NULL;

    -- Local část nesmí obsahovat dvě tečky za sebou
    IF CHARINDEX(N'..', @local) > 0 RETURN NULL;

    -- Krok 5: Validace domain části
    IF LEN(@domain) = 0 RETURN NULL;

    -- Doména nesmí začínat nebo končit tečkou
    IF LEFT(@domain, 1) = N'.' RETURN NULL;
    IF RIGHT(@domain, 1) = N'.' RETURN NULL;

    -- Doména musí obsahovat alespoň jednu tečku
    IF CHARINDEX(N'.', @domain) = 0 RETURN NULL;

    -- TLD (část za poslední tečkou) musí mít min 2 znaky
    DECLARE @last_dot INT =
        LEN(@domain) - CHARINDEX(N'.', REVERSE(@domain)) + 1;
    DECLARE @tld NVARCHAR(20) =
        SUBSTRING(@domain, @last_dot + 1, LEN(@domain));
    IF LEN(@tld) < 2 RETURN NULL;

    -- TLD musí obsahovat pouze písmena
    IF @tld LIKE N'%[^a-z]%' RETURN NULL;

    RETURN @local + N'@' + @domain;
END
GO


