USE [Opendata]
GO

/****** Object:  Table [dbo].[cfg_EUmembers]    Script Date: 06.06.2026 22:40:57 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[cfg_EUmembers](
	[ID] [int] NULL,
	[cEUM_Zeme] [nvarchar](60) NULL,
	[cEUM_ISO] [varchar](2) NULL,
	[DatCreateRAW] [nvarchar](50) NULL,
	[DatKonec] [datetime2](0) NULL,
	[cEUM_Abbrev] [varchar](5) NULL,
	[cEUM_Popula] [varchar](15) NULL,
	[cEUM_Area] [varchar](10) NULL,
	[cEUM_TopCity] [nvarchar](15) NULL,
	[cEUM_GDP] [varchar](15) NULL,
	[cEUM_GDPcapita] [decimal](10, 3) NULL,
	[cEUM_CurrNazev] [nvarchar](20) NULL,
	[cEUMCurrZkr] [nvarchar](3) NULL,
	[cEUM_HDI] [varchar](10) NULL,
	[cEUM_Seats] [tinyint] NULL,
	[cEUM_Langua] [nvarchar](35) NULL,
	[cEUM_SchengFrom] [varchar](20) NULL,
	[cEUM_SchengImplem] [varchar](20) NULL,
	[cEUM_SchengPozn] [nvarchar](100) NULL,
	[cEUM_PolitSyst] [nvarchar](50) NULL,
	[DatImport] [datetime2](0) NULL,
	[Aktivni] [bit] NULL
) ON [PRIMARY]
GO


