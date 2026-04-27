-- Sample Cloud Spanner schema (GoogleSQL) for TiShift demos and tests.
-- Covers: interleaved tables, ARRAY columns, commit timestamps,
--         generated columns, row deletion policy, FK, indexes, JSON, BYTES.

-- Singers table (root of interleave hierarchy)
CREATE TABLE Singers (
    SingerId   INT64 NOT NULL,
    FirstName  STRING(1024),
    LastName   STRING(1024),
    BirthDate  DATE,
    Bio        STRING(MAX),
    Tags       ARRAY<STRING(100)>,              -- BLOCKER-2: ARRAY column
    Metadata   JSON,
    Photo      BYTES(MAX),                       -- large binary
    CreatedAt  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),  -- WARNING-1
    UpdatedAt  TIMESTAMP OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY(SingerId);

-- Albums table (interleaved in Singers) — BLOCKER-1
CREATE TABLE Albums (
    SingerId   INT64 NOT NULL,
    AlbumId    INT64 NOT NULL,
    AlbumTitle STRING(MAX),
    ReleaseDate DATE,
    Genre      STRING(100),
    TrackList  ARRAY<STRING(200)>,              -- BLOCKER-2: ARRAY column
    Rating     FLOAT64,
    IsActive   BOOL,                             -- WARNING-10
    CreatedAt  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
) PRIMARY KEY(SingerId, AlbumId),
  INTERLEAVE IN PARENT Singers ON DELETE CASCADE;

-- Songs table (interleaved in Albums, 3-level hierarchy)
CREATE TABLE Songs (
    SingerId   INT64 NOT NULL,
    AlbumId    INT64 NOT NULL,
    TrackId    INT64 NOT NULL,
    SongName   STRING(MAX),
    Duration   INT64,                            -- milliseconds
    SongGenre  STRING(100),
    Lyrics     STRING(MAX),
) PRIMARY KEY(SingerId, AlbumId, TrackId),
  INTERLEAVE IN PARENT Albums ON DELETE CASCADE;

-- Venues table (standalone, not interleaved)
CREATE TABLE Venues (
    VenueId    INT64 NOT NULL,
    VenueName  STRING(1024) NOT NULL,
    Capacity   INT64,
    Location   STRING(2048),
    Revenue    NUMERIC,                          -- WARNING-7: NUMERIC(38,9)
    PopularDays ARRAY<STRING(10)>,               -- BLOCKER-2: ARRAY column
) PRIMARY KEY(VenueId);

-- Concerts table with FK (not interleaved)
CREATE TABLE Concerts (
    ConcertId  INT64 NOT NULL,
    VenueId    INT64 NOT NULL,
    SingerId   INT64 NOT NULL,
    ConcertDate DATE NOT NULL,
    TicketPrice NUMERIC,
    Notes      STRING(MAX),
    CreatedAt  TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
    CONSTRAINT FK_Concerts_Venues FOREIGN KEY (VenueId) REFERENCES Venues(VenueId),
    CONSTRAINT FK_Concerts_Singers FOREIGN KEY (SingerId) REFERENCES Singers(SingerId),
) PRIMARY KEY(ConcertId)
, ROW DELETION POLICY (OLDER_THAN(CreatedAt, INTERVAL 365 DAY));  -- WARNING-3

-- Generated column example
CREATE TABLE TicketSales (
    SaleId     INT64 NOT NULL,
    ConcertId  INT64 NOT NULL,
    SeatNumber STRING(20),
    Price      NUMERIC,
    Quantity   INT64,
    TotalAmount NUMERIC AS (Price * Quantity) STORED,  -- WARNING-4: generated column
    SoldAt     TIMESTAMP NOT NULL OPTIONS (allow_commit_timestamp = true),
    CONSTRAINT FK_TicketSales_Concerts FOREIGN KEY (ConcertId) REFERENCES Concerts(ConcertId),
) PRIMARY KEY(SaleId);

-- Secondary indexes
CREATE INDEX SingersByLastName ON Singers(LastName);
CREATE INDEX AlbumsByTitle ON Albums(SingerId, AlbumTitle);
CREATE INDEX ConcertsByDate ON Concerts(ConcertDate DESC);
CREATE UNIQUE INDEX VenuesByName ON Venues(VenueName);

-- NULL-filtered index (Spanner-specific)
CREATE NULL_FILTERED INDEX SingersByBirthDate ON Singers(BirthDate);

-- Change stream for CDC
CREATE CHANGE STREAM AllTablesStream FOR ALL;
