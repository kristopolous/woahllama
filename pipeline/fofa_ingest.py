#!/usr/bin/env python3
"""Parse every graflex FOFA snapshot into a private SQLite DB (fofa/fofa.db),
then load the independent probe list (working/notworking). Real IPs -> gitignored.

The captures arrive in two layouts and both are read:

  tmp/graflex/fofa-results-*.txt                 the original flat drop
  tmp/graflex/graflex/<rundate>/fofa-results-*   one directory per scan run
  tmp/graflex/graflex/<rundate>/fofa/<svc>-*     newer runs, service in the name

Only Ollama is in scope. Where the filename states the service, that is trusted
and everything but `ollama-*` is discarded. The older runs do not name a service
and are not all Ollama sweeps - one is a port-28017 MongoDB sweep - so an asset
from those is kept only when its FOFA struct_info parses as an Ollama model
catalogue. That is conservative: a genuine Ollama host that had pulled no models
at scan time looks identical to a non-Ollama host and is dropped.

Each run is a separate dated observation, so a host seen in several runs gets
several sightings rather than collapsing to a latest-known state. The sighting
timestamp is FOFA's own `mtime` for the asset (when FOFA last saw it), not the
time we ran the query. `fofa_sighting` holds those; `fofa_host` is kept as the
latest-row-per-host view that older consumers expect."""
import os, re, json, sys, sqlite3, multiprocessing as mp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAFLEX = os.path.join(ROOT, "tmp", "graflex")
DB = os.path.join(ROOT, "fofa", "fofa.db")
BLOB = re.compile(r'id="__NUXT_DATA__">(.*?)</script>', re.S)
# country appears in a different position in each generation of the naming
# scheme, so try them in turn rather than assuming one layout
FNAME_PATS = (
    re.compile(r'^fofa-results-[0-9a-f]+-([A-Z]{2})-(\d+)-'),      # <qhash>-<CC>-<port>
    re.compile(r'^fofa-results-([A-Z]{2})-(\d+)-'),                # <CC>-<port>
    re.compile(r'^[a-z0-9.]+-[0-9a-f]+-([A-Z]{2})-(\d+)-'),        # <svc>-<qhash>-<CC>-<port>
)
SVC_PAT = re.compile(r'^([a-z0-9.]+)-[0-9a-f]{6,}-')
RUNDATE = re.compile(r'(\d{8})\d{6}')


def file_country(name):
    for p in FNAME_PATS:
        m = p.search(name)
        if m and m.group(1) != "any":
            return m.group(1)
    return None


def file_service(name):
    """The service the query targeted, when the filename says so. Files whose
    name begins `fofa-results-` predate the multi-service scanner and carry no
    such claim - those return None and are filtered on their contents instead."""
    if name.startswith("fofa-results-"):
        return None
    m = SVC_PAT.match(name)
    return m.group(1) if m else None


def ollama_models(models_json):
    """True when a FOFA struct_info block looks like an Ollama model catalogue:
    at least one entry with a name. FOFA only fills struct_info for services it
    fingerprints, and for these sweeps that is Ollama's /api/tags."""
    try:
        return any(m and m[0] for m in json.loads(models_json))
    except Exception:
        return False
TAGS = ("ShallowReactive", "Reactive", "Ref", "EmptyRef")

def extract(path):
    try:
        html = open(path, encoding='utf-8', errors='replace').read()
    except Exception:
        return []
    m = BLOB.search(html)
    if not m: return []
    try:
        pool = json.loads(m.group(1))
    except Exception:
        return []
    def node(i):
        v = pool[i] if isinstance(i, int) and 0 <= i < len(pool) else i
        while isinstance(v, list) and v and isinstance(v[0], str) and v[0] in TAGS:
            v = pool[v[1]]
        return v
    def val(i, depth=0):
        if not isinstance(i, int) or i < 0 or i >= len(pool): return i
        if depth > 12: return None
        v = pool[i]
        if isinstance(v, dict):
            return {k: val(x, depth+1) for k, x in v.items()}
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in TAGS:
                return val(v[1], depth+1)
            return [val(x, depth+1) for x in v]
        return v
    try:
        root = node(1); data = node(root['data'])
        key = next(k for k in data if isinstance(k, str) and k.startswith('result-search-assets'))
        inner = node(data[key]); body = node(inner['data']); idxs = node(body['assets'])
    except Exception:
        return []
    base = os.path.basename(path)
    country = file_country(base)
    out = []
    for ai in idxs:
        a = val(ai)
        if not isinstance(a, dict): continue
        si = a.get('struct_info') or []
        models = [[s.get('name'), s.get('parameter_size'), s.get('quantization_level'), s.get('publisher')]
                  for s in si if isinstance(s, dict)]
        out.append((a.get('host') or f"{a.get('ip')}:{a.get('port')}", a.get('ip'), a.get('port'),
                    a.get('mtime'), 1 if a.get('is_honeypot') else 0, a.get('asn_org') or "",
                    a.get('cloud_name') or "", country, json.dumps(models)))
    return out

def find_files():
    """Every FOFA capture, as (path, service-claimed-by-filename, run-id)."""
    out = []
    flat = [f for f in os.listdir(GRAFLEX) if f.startswith("fofa-results-")]
    for f in flat:
        m = RUNDATE.search(f)
        out.append((os.path.join(GRAFLEX, f), None, m.group(1) if m else "flat"))
    runs = os.path.join(GRAFLEX, "graflex")
    if os.path.isdir(runs):
        for run in sorted(os.listdir(runs)):
            d = os.path.join(runs, run)
            if not os.path.isdir(d):
                continue
            rid = RUNDATE.match(run).group(1) if RUNDATE.match(run) else run
            # older runs: captures sit directly in the run directory
            for f in os.listdir(d):
                if f.startswith("fofa-results-"):
                    out.append((os.path.join(d, f), None, rid))
            # newer runs: a fofa/ subdirectory, service named in the file
            sub = os.path.join(d, "fofa")
            if os.path.isdir(sub):
                for f in os.listdir(sub):
                    out.append((os.path.join(sub, f), file_service(f), rid))
    return out


def _parse(job):
    path, svc, rid = job
    return svc, rid, extract(path)


def build_fofa():
    jobs = find_files()
    # Drop the non-Ollama services before parsing: on a run with 8,400 captures
    # across eight services this is most of the work avoided.
    jobs = [j for j in jobs if j[1] in (None, "ollama")]
    runs = sorted({j[2] for j in jobs})
    print(f"graflex fofa captures: {len(jobs)} across {len(runs)} runs "
          f"({', '.join(runs)})", file=sys.stderr)

    # (host, mtime-day) -> row. A run re-reports hosts it has seen before with
    # the same mtime, so the day is what makes a sighting distinct; the richest
    # struct_info wins a tie.
    seen = {}
    kept = dropped = done = empty = raw_rows = 0
    with mp.Pool(min(8, os.cpu_count() or 4)) as pool:
        for svc, rid, rows in pool.imap_unordered(_parse, jobs, chunksize=16):
            done += 1
            if not rows: empty += 1
            raw_rows += len(rows)
            if done % 2500 == 0:
                print(f"  parsed {done}/{len(jobs)}  sightings={len(seen)}", file=sys.stderr)
            for r in rows:
                h, mt = r[0], r[3] or ""
                if not h:
                    continue
                # filename did not claim a service: keep only assets that
                # evidence themselves as Ollama through struct_info
                if svc is None and not ollama_models(r[8]):
                    dropped += 1
                    continue
                kept += 1
                k = (h, mt[:10])
                cur = seen.get(k)
                if cur is None or len(r[8]) > len(cur[8]):
                    seen[k] = r + (rid, mt[:10])

    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS fofa_sighting;
      CREATE TABLE fofa_sighting(host TEXT, ip TEXT, port INTEGER, mtime TEXT,
                                 honeypot INTEGER, asn_org TEXT, cloud TEXT,
                                 country TEXT, models TEXT, run TEXT, day TEXT,
                                 PRIMARY KEY(host, day));
      DROP TABLE IF EXISTS fofa_host;
      CREATE TABLE fofa_host(host TEXT PRIMARY KEY, ip TEXT, port INTEGER, mtime TEXT,
                             honeypot INTEGER, asn_org TEXT, cloud TEXT, country TEXT, models TEXT);
      DROP TABLE IF EXISTS fofa_model;
      CREATE TABLE fofa_model(host TEXT, name TEXT, param_size TEXT, quant TEXT, publisher TEXT);
    """)
    c.executemany("INSERT OR REPLACE INTO fofa_sighting VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  seen.values())

    # latest row per host, for the consumers that still want a single state
    best = {}
    for r in seen.values():
        cur = best.get(r[0])
        if cur is None or (r[3] or "") > (cur[3] or "") or \
           (r[3] == cur[3] and len(r[8]) > len(cur[8])):
            best[r[0]] = r
    c.executemany("INSERT OR REPLACE INTO fofa_host VALUES (?,?,?,?,?,?,?,?,?)",
                  [r[:9] for r in best.values()])
    for r in best.values():
        for name, ps, q, pub in json.loads(r[8]):
            c.execute("INSERT INTO fofa_model VALUES (?,?,?,?,?)", (r[0], name, ps, q, pub))
    c.executescript("""
      CREATE INDEX idx_model_host ON fofa_model(host);
      CREATE INDEX idx_host_mtime ON fofa_host(mtime);
      CREATE INDEX idx_sight_host ON fofa_sighting(host);
      CREATE INDEX idx_sight_day  ON fofa_sighting(day);
    """)
    con.commit()
    hp = c.execute("SELECT COUNT(*) FROM fofa_host WHERE honeypot=1").fetchone()[0]
    wm = c.execute("SELECT COUNT(*) FROM fofa_host WHERE models!='[]'").fetchone()[0]
    multi = c.execute("SELECT COUNT(*) FROM (SELECT host FROM fofa_sighting"
                      " GROUP BY host HAVING COUNT(*) > 1)").fetchone()[0]
    print(f"files={len(jobs)} empty(no-result)={empty} raw_asset_rows={raw_rows}", file=sys.stderr)
    print(f"  kept={kept} dropped-as-not-ollama={dropped}", file=sys.stderr)
    print(f"fofa_sighting: {len(seen)} dated sightings, {len(best)} hosts "
          f"({multi} seen on more than one day)", file=sys.stderr)
    print(f"fofa_host: {len(best)}  with-models: {wm}  honeypot: {hp}", file=sys.stderr)
    for mo, n in c.execute("SELECT day, COUNT(*) FROM fofa_sighting WHERE day!=''"
                           " GROUP BY day ORDER BY day"):
        print(f"   {mo}: {n}", file=sys.stderr)
    con.close()


def load_probe():
    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS probe;
      CREATE TABLE probe(host TEXT PRIMARY KEY, status TEXT, checked TEXT, version TEXT,
                         reason TEXT, url TEXT, models TEXT);
    """)
    def norm(h):  # working.json host is "ip:port"; align to fofa_host.host "https://ip:port" or "ip:port"
        return h
    w = json.load(open(os.path.join(ROOT, "ollama-working.json")))
    for o in w:
        c.execute("INSERT OR REPLACE INTO probe VALUES (?,?,?,?,?,?,?)",
                  (o.get('host'), 'working', o.get('checked'), o.get('version') or '',
                   '', o.get('url') or '', json.dumps(o.get('models') or [])))
    nw = json.load(open(os.path.join(ROOT, "ollama-notworking.json")))
    it = nw.values() if isinstance(nw, dict) else nw
    for o in it:
        c.execute("INSERT OR REPLACE INTO probe VALUES (?,?,?,?,?,?,?)",
                  (o.get('host'), 'notworking', o.get('checked'), '', o.get('reason') or '',
                   o.get('url') or '', '[]'))
    con.commit()
    nw_c = c.execute("SELECT COUNT(*) FROM probe WHERE status='notworking'").fetchone()[0]
    w_c = c.execute("SELECT COUNT(*) FROM probe WHERE status='working'").fetchone()[0]
    print(f"probe: working={w_c} notworking={nw_c}", file=sys.stderr)
    con.close()

if __name__ == "__main__":
    if "--probe-only" not in sys.argv:
        build_fofa()
    load_probe()
