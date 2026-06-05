USE [Opendata]
GO
/****** Object:  UserDefinedFunction [dbo].[fn_SplitContacts]    Script Date: 05.06.2026 19:54:50 ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO


-- ============================================================
-- fn_SplitContacts
-- Rozdělí vícehodnotové pole na jednotlivé tokeny
--
-- Parametry:
--   @val        - vstupní řetězec (telefony, emaily, ...)
--   @delimiters - řetězec oddělovačů, každý znak = jeden oddělovač
--                 např. ';,'  nebo  ';'
--
-- Vrací:
--   Poradi      - pořadí tokenu (1, 2, 3...)
--   Hodnota     - jeden token, trimovaný, neprázdný
--
-- Volání:
--   CROSS APPLY infobase.dbo.fn_SplitContacts(d.D_Tel, ';,')
--   CROSS APPLY infobase.dbo.fn_SplitContacts(d.D_Email, ';')
--
-- Poznámky:
--   • Mezera NENÍ oddělovač - číslo '+420 731 173 068' zůstane celé
--   • Prázdné tokeny jsou přeskočeny
--   • Funkce nevolá fn_CleanString - to je zodpovědnost volajícího
-- ============================================================
ALTER   FUNCTION [dbo].[fn_SplitContacts]
(
    @val        NVARCHAR(1000),
    @delimiters NVARCHAR(20)
)
RETURNS @result TABLE
(
    Poradi  INT,
    Hodnota NVARCHAR(500)
)
AS
BEGIN
    IF @val IS NULL OR LEN(LTRIM(RTRIM(@val))) = 0
        RETURN;

    -- Nahradit všechny oddělovače pipe-znakem |
    DECLARE @normalized NVARCHAR(1000) = @val;
    DECLARE @i INT = 1;
    DECLARE @delim_len INT = LEN(@delimiters);

    WHILE @i <= @delim_len
    BEGIN
        SET @normalized = REPLACE(
            @normalized,
            SUBSTRING(@delimiters, @i, 1),
            N'|'
        );
        SET @i += 1;
    END

    -- Přidat | na konec pro jednotný parsing
    SET @normalized = @normalized + N'|';

    -- Splitovat podle |
    DECLARE @poradi  INT = 0;
    DECLARE @pos     INT;
    DECLARE @token   NVARCHAR(500);

    WHILE LEN(@normalized) > 0
    BEGIN
        SET @pos = CHARINDEX(N'|', @normalized);
        IF @pos = 0 BREAK;

        SET @token = LTRIM(RTRIM(SUBSTRING(@normalized, 1, @pos - 1)));
        SET @normalized = SUBSTRING(@normalized, @pos + 1, LEN(@normalized));

        -- Přeskočit prázdné tokeny
        IF LEN(@token) = 0 CONTINUE;

        SET @poradi += 1;
        INSERT @result (Poradi, Hodnota) VALUES (@poradi, @token);
    END

    RETURN;
END

