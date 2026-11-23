-- Kungal galgame database schema (generated)
CREATE TABLE works (
    id                   TEXT PRIMARY KEY,
    display_name         TEXT,
    name_ja              TEXT,
    name_zh              TEXT,
    name_en              TEXT,
    name_latin           TEXT,
    cover_url            TEXT,
    cover_hash           TEXT,
    cover_width          INTEGER,
    cover_height         INTEGER,
    cover_sexual         TEXT,
    cover_sfw_url        TEXT,
    banner_url           TEXT,
    release_date         TEXT,
    release_date_precision TEXT,
    maker_id             TEXT,
    maker_name           TEXT,
    is_nsfw              INTEGER,
    is_published         INTEGER,
    view_count           INTEGER,
    like_count           INTEGER,
    rating_score         REAL,
    rating_count         INTEGER,
    resource_platforms   TEXT,
    resource_languages   TEXT,
    resource_updated_at  TEXT,
    in_resource_lib      INTEGER DEFAULT 0,
    in_gallib            INTEGER DEFAULT 0,
    detail_url           TEXT,
    fetched_at           TEXT
, in_calendar INTEGER DEFAULT 0);

CREATE INDEX idx_works_name ON works(display_name);

CREATE INDEX idx_works_date ON works(release_date);

CREATE TABLE crawl_state (
    dataset   TEXT,
    page      INTEGER,
    ok        INTEGER,
    n_items   INTEGER,
    total     INTEGER,
    fetched_at TEXT,
    PRIMARY KEY (dataset, page)
);

CREATE TABLE calendar_state (
        month TEXT PRIMARY KEY, ok INTEGER, n_items INTEGER, fetched_at TEXT);

CREATE TABLE api_state (
    endpoint TEXT, sort TEXT, page INTEGER, ok INTEGER, n_items INTEGER, total INTEGER,
    fetched_at TEXT, PRIMARY KEY (endpoint, sort, page)
);
