USE [Opendata]
GO

/****** Object:  Table [dbo].[src_Jmena]    Script Date: 05.06.2026 21:39:40 ******/
SET ANSI_NULLS ON
GO

SET QUOTED_IDENTIFIER ON
GO

CREATE TABLE [dbo].[src_Jmena](
	[ID] [int] NOT NULL,
	[R_Jmeno] [varchar](30) NULL,
	[R_Sex] [varchar](1) NULL,
	[R_Cetnost] [tinyint] NULL,
	[R_Rank] [smallint] NULL,
 CONSTRAINT [PK_src_Jmena] PRIMARY KEY CLUSTERED 
(
	[ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO


