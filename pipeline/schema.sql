PRAGMA journal_mode=WAL;
PRAGMA synchronous=OFF;

CREATE TABLE IF NOT EXISTS source(
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  repo TEXT,
  path TEXT,
  discovery TEXT           -- how this source finds servers (fofa/shodan/accumulated)
);

-- one row per commit that changed the source's data file
CREATE TABLE IF NOT EXISTS snapshot(
  id INTEGER PRIMARY KEY,
  source_id INT NOT NULL,
  seq INT NOT NULL,        -- 0-based chronological index within the source
  commit_sha TEXT NOT NULL,
  ts INT NOT NULL,
  n_servers INT,
  n_model_rows INT,
  UNIQUE(source_id, seq)
);

CREATE TABLE IF NOT EXISTS server(
  id INTEGER PRIMARY KEY,
  url TEXT UNIQUE,         -- canonical scheme://host:port
  host TEXT,
  port INT,
  ip TEXT,                 -- NULL when host is a domain name
  ip_int INT,
  o1 INT, o2 INT           -- first two octets, for the bubble chart
);

CREATE TABLE IF NOT EXISTS model(
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,        -- full "base:tag" as reported
  base TEXT,               -- name without the tag
  tag TEXT
);

-- run-length encoded presence: server was in every snapshot from
-- start_seq..end_seq inclusive, then vanished (or the history ended)
CREATE TABLE IF NOT EXISTS presence(
  source_id INT NOT NULL,
  server_id INT NOT NULL,
  start_seq INT NOT NULL, end_seq INT NOT NULL,
  start_ts INT NOT NULL,  end_ts INT NOT NULL,
  n_snap INT NOT NULL
);

CREATE TABLE IF NOT EXISTS server_model(
  source_id INT NOT NULL,
  server_id INT NOT NULL,
  model_id INT NOT NULL,
  start_seq INT NOT NULL, end_seq INT NOT NULL,
  start_ts INT NOT NULL,  end_ts INT NOT NULL,
  n_snap INT NOT NULL
);
