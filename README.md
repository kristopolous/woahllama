# woah…llama

Eighteen months of unsecured Ollama servers, reconstructed from the commit
histories of scanners that publish what they find, plus an independent
current-snapshot survey. The site reads it back out as an interactive report in
two chapters:

- **Chapter 1 — What's actually out there.** The survey of the real, open
  servers built from the two feeds that verify their hosts: geography (which
  labs' models each country runs), vendors over time, individual models,
  parameter size and quantisation, operator behaviour, and coordinated block
  arrivals and departures.
- **Chapter 2 — Unexpected behavior.** Hundreds of live hosts in one scanner's
  feed that answer the Ollama API from a fixed script: the same frozen model
  list everywhere, byte-identical sizes, four rotating version strings, and
  chat replies assembled from a tiny phrase bank. What causes it is left open.

## Run it

The built site data is committed, so you can serve it immediately:

```sh
./serve.sh 8000     # then open http://localhost:8000
```

The page loads its data with `fetch()`, so it must be served rather than opened
as a file.

## Reproduce the data

```sh
./setup.sh          # clones the upstream scanners, fetches DB-IP, builds everything
```

`setup.sh` needs `git`, `python3` (standard library only), and `curl`. It clones
the three upstream repositories (their commit history is the dataset), downloads
the DB-IP city-lite database, ingests ~77M observations into a run-length-encoded
SQLite database, and rebuilds `site/data/*.json`. Budget a few minutes and about
half a gigabyte of clones.

To rebuild only the derived data after `survey.db` exists:

```sh
./rebuild.sh
```

## How the pipeline fits together

```
upstream scanners (git history)
        │  pipeline/ingest.py        run-length encode -> survey.db
        │  pipeline/geo.py           IP -> country / city / lat-lon (DB-IP)
        │  pipeline/vendors.py       model -> lab, lab HQ, uncensored?
        │  pipeline/ollama_library.py  tag -> manifest digest -> real size
        │  pipeline/modelmeta.py     parameter count, size band, quantisation
        │  pipeline/clusters.py      identical-catalogue blocks
        │  pipeline/strange.py       the Chapter 2 analysis
        └─ pipeline/build.py         survey.db -> site/data/*.json
                                     site/  static page, no dependencies
```

| file | what it is |
|---|---|
| `pipeline/gitblobs.py` | streams file revisions out of a repo via one `git cat-file --batch` |
| `pipeline/parse.py` | per-source parsers and URL canonicalisation |
| `pipeline/schema.sql` | the interval schema |
| `pipeline/mask.py` | redacts host identity for anything shipped publicly |
| `site/charts.js` | small SVG charting primitives, no dependencies |
| `site/app.js` | page wiring, map, scatter, canvas bubbles |

## Notes on what the data can and can't say

- **Only aggregates are published.** This repository ships counts, shares, and
  distributions. It does not ship the list of reachable addresses; IPs in the
  site are masked to their /16, and the raw host-level captures are not included.
- **Run-length encoding.** Consecutive snapshots are ~99.5% identical, so
  presence is stored as intervals ("present in every snapshot from A to B").
  ~77M observations compress to ~468k rows losslessly.
- **Three feeds, used differently.** Two verify their hosts and form the
  Chapter 1 survey. The third scrapes Shodan indiscriminately; it is kept out of
  the trend charts and is the basis of Chapter 2.
- **`-cloud` tags are dropped** everywhere: they proxy to Ollama's hosted
  service and commit no local weights.
- **The most recent two days are trimmed**, since a half-finished day of
  scanning reads as a real drop in every trend.

IP geolocation by [DB-IP](https://db-ip.com) (CC BY 4.0). Lab attribution is by
base-model lineage.
