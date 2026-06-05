USE [Opendata]
GO

/****** Object:  UserDefinedFunction [dbo].[fn_CleanStringExt]    Script Date: 05.06.2026 19:53:48 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO




-- ============================================================
-- fn_CleanStringExt
-- Rozšířené čištění - volá fn_CleanString + Unicode normalizace
--
-- Navíc normalizuje:
--   • En-dash (8211), Em-dash (8212)  → standardní pomlčka -
--   • Trojtečka (8230)                → ...
--   • Typografické uvozovky (8220, 8221, 8222) → "
--   • Typografické apostrofy (8216, 8217)      → '
--
-- Použití: jména, příjmení, názvy firem, adresy, města
-- NEPOUŽÍVAT pro: telefony, emaily, URL
--   (ty volají přímo fn_CleanString)
-- ============================================================
CREATE   FUNCTION [dbo].[fn_CleanStringExt]
(
    @val NVARCHAR(500)
)
RETURNS NVARCHAR(500)
AS
BEGIN
    IF @val IS NULL RETURN NULL;

    -- Základ: technické čištění
    DECLARE @result NVARCHAR(500) = [dbo].[fn_CleanString](@val);

    IF @result IS NULL RETURN NULL;

    -- En-dash, Em-dash → standardní pomlčka
    SET @result = REPLACE(@result, NCHAR(8211), N'-');
    SET @result = REPLACE(@result, NCHAR(8212), N'-');

    -- Trojtečka → tři tečky
    SET @result = REPLACE(@result, NCHAR(8230), N'...');

    -- Typografické uvozovky → standardní "
    SET @result = REPLACE(@result, NCHAR(8220), N'"');   -- "
    SET @result = REPLACE(@result, NCHAR(8221), N'"');   -- "
    SET @result = REPLACE(@result, NCHAR(8222), N'"');   -- „

    -- Typografické apostrofy → standardní '
    SET @result = REPLACE(@result, NCHAR(8216), N'''');  -- '
    SET @result = REPLACE(@result, NCHAR(8217), N'''');  -- '

    -- Po náhradách znovu sloučit mezery (pro jistotu)
    WHILE CHARINDEX(N'  ', @result) > 0
        SET @result = REPLACE(@result, N'  ', N' ');

    SET @result = LTRIM(RTRIM(@result));

    IF LEN(@result) = 0 RETURN NULL;

    RETURN @result;
END

GO


