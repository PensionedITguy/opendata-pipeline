USE [Opendata]
GO

/****** Object:  UserDefinedFunction [dbo].[fn_CleanString]    Script Date: 05.06.2026 19:52:45 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO



-- ============================================================
-- fn_CleanString
-- Technické čištění řetězce - univerzální základ
--
-- Odstraňuje:
--   • Control chars ASCII 1-31
--   • DEL (127)
--   • NBSP (160)           → mezera (pak sloučena)
--   • Zero-width space (8203)
--   • Zero-width no-break space / BOM (65279)
--   • Soft hyphen (173)    → odstraněn (ne nahrazen)
--   • Vícenásobné mezery   → jedna mezera
--   • Trim
--   • Prázdný výsledek     → NULL
--
-- Nezasahuje do: interpunkce, závorek, pomlček, teček,
--               speciálních znaků URL/email/tel
-- ============================================================
CREATE   FUNCTION [dbo].[fn_CleanString]
(
    @val NVARCHAR(500)
)
RETURNS NVARCHAR(500)
AS
BEGIN
    IF @val IS NULL RETURN NULL;

    DECLARE @result NVARCHAR(500) = @val;
    DECLARE @i INT = 1;

    -- Control chars 1-31
    WHILE @i <= 31
    BEGIN
        SET @result = REPLACE(@result, NCHAR(@i), N'');
        SET @i += 1;
    END

    -- DEL
    SET @result = REPLACE(@result, NCHAR(127),  N'');

    -- NBSP → mezera (sloučí se níže)
    SET @result = REPLACE(@result, NCHAR(160),  N' ');

    -- Soft hyphen → odstranit
    SET @result = REPLACE(@result, NCHAR(173),  N'');

    -- Zero-width space → odstranit
    SET @result = REPLACE(@result, NCHAR(8203), N'');

    -- Zero-width no-break space / BOM → odstranit
    SET @result = REPLACE(@result, NCHAR(65279), N'');

    -- Sloučit vícenásobné mezery
    WHILE CHARINDEX(N'  ', @result) > 0
        SET @result = REPLACE(@result, N'  ', N' ');

    SET @result = LTRIM(RTRIM(@result));

    IF LEN(@result) = 0 RETURN NULL;

    RETURN @result;
END

GO


