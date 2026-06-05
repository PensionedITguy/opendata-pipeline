USE [Z_ORstagg]
GO

/****** Object:  Table [dbo].[src_OR_Udaje]    Script Date: 05.06.2026 21:08:34 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[src_OR_Udaje](
	[UdajID] [int] IDENTITY(1,1) NOT NULL,
	[EntityID] [int] NOT NULL,
	[ICO] [varchar](20) NOT NULL,
	[UdajTypKod] [nvarchar](50) NULL,
	[UdajTypNazev] [nvarchar](500) NULL,
	[ParentUdajTypKod] [nvarchar](50) NULL,
	[Hlavicka] [nvarchar](500) NULL,
	[HodnotaText] [nvarchar](max) NULL,
	[OsobaTyp] [char](1) NULL,
	[ZapisDatum] [date] NULL,
	[VymazDatum] [date] NULL,
	[FO_Jmeno] [nvarchar](200) NULL,
	[FO_Prijmeni] [nvarchar](500) NULL,
	[FO_TitulPred] [nvarchar](50) NULL,
	[FO_TitulZa] [nvarchar](500) NULL,
	[FO_Narozeni] [date] NULL,
	[FO_StatKod] [nvarchar](200) NULL,
	[FO_StatNazev] [nvarchar](100) NULL,
	[PO_ICO] [char](8) NULL,
	[PO_Nazev] [nvarchar](max) NULL,
	[PO_EUID] [nvarchar](50) NULL,
	[Funkce] [nvarchar](500) NULL,
	[FunkceOd] [date] NULL,
	[FunkceDo] [date] NULL,
	[ClenstviOd] [date] NULL,
	[ClenstviDo] [date] NULL,
	[AdrObec] [nvarchar](500) NULL,
	[AdrCastObce] [nvarchar](100) NULL,
	[AdrUlice] [nvarchar](500) NULL,
	[AdrCisloPo] [nvarchar](20) NULL,
	[AdrCisloOr] [nvarchar](200) NULL,
	[AdrPSC] [char](5) NULL,
	[AdrOkres] [nvarchar](100) NULL,
	[AdrStatNazev] [nvarchar](100) NULL,
	[FinHodnota] [decimal](18, 2) NULL,
	[FinHodnotaTyp] [nvarchar](20) NULL,
	[FinSplaceni] [decimal](18, 2) NULL,
	[FinSplaceniTyp] [nvarchar](20) NULL,
	[FinSouhrn] [decimal](18, 2) NULL,
	[FinSouhrnTyp] [nvarchar](20) NULL,
	[AkciePodoba] [nvarchar](50) NULL,
	[AkcieTyp] [nvarchar](50) NULL,
	[AkciePocet] [int] NULL,
	[DruhPodilu] [nvarchar](500) NULL,
	[SpZnSoudKod] [nvarchar](10) NULL,
	[SpZnSoudNazev] [nvarchar](100) NULL,
	[SpZnOddil] [nvarchar](10) NULL,
	[SpZnVlozka] [nvarchar](20) NULL,
	[DatLoad] [datetime] NOT NULL,
 CONSTRAINT [PK_OR_Udaje] PRIMARY KEY CLUSTERED 
(
	[UdajID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [STAGING_DATA]
) ON [STAGING_DATA] TEXTIMAGE_ON [STAGING_DATA]
GO

ALTER TABLE [dbo].[src_OR_Udaje] ADD  CONSTRAINT [DF_OR_Udaje_DatLoad]  DEFAULT (getdate()) FOR [DatLoad]
GO

ALTER TABLE [dbo].[src_OR_Udaje]  WITH CHECK ADD  CONSTRAINT [FK_OR_Udaje_Entity] FOREIGN KEY([EntityID])
REFERENCES [dbo].[src_OR_Entity] ([EntityID])
GO

ALTER TABLE [dbo].[src_OR_Udaje] CHECK CONSTRAINT [FK_OR_Udaje_Entity]
GO


