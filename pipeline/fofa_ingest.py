#!/usr/bin/env python3
"""Parse every graflex FOFA snapshot into a private SQLite DB (fofa/fofa.db),
then load the independent probe list (working/notworking). Real IPs -> gitignored."""
import os, re, json, sys, sqlite3, multiprocessing as mp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAFLEX = os.path.join(ROOT, "tmp", "graflex")
DB = os.path.join(ROOT, "fofa", "fofa.db")
BLOB = re.compile(r'id="__NUXT_DATA__">(.*?)</script>', re.S)
FNAME = re.compile(r'fofa-results-[0-9a-f]+-([A-Z0-9]+)-(\d+)-')
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
    fm = FNAME.search(os.path.basename(path))
    country = fm.group(1) if fm else None
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

def build_fofa():
    files = [os.path.join(GRAFLEX, f) for f in os.listdir(GRAFLEX) if f.startswith('fofa-results-')]
    print(f"graflex files: {len(files)}", file=sys.stderr)
    best = {}   # host -> row, dedup keeping most recent mtime (most models as tiebreak)
    done = empty = raw_rows = 0
    with mp.Pool(min(8, os.cpu_count() or 4)) as pool:
        for rows in pool.imap_unordered(extract, files, chunksize=16):
            done += 1
            if not rows: empty += 1
            raw_rows += len(rows)
            if done % 2500 == 0: print(f"  parsed {done}/{len(files)}  hosts={len(best)}", file=sys.stderr)
            for r in rows:
                h = r[0]
                if not h: continue
                cur = best.get(h)
                if cur is None or (r[3] or '') > (cur[3] or '') or \
                   (r[3] == cur[3] and len(r[8]) > len(cur[8])):
                    best[h] = r
    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS fofa_host;
      CREATE TABLE fofa_host(host TEXT PRIMARY KEY, ip TEXT, port INTEGER, mtime TEXT,
                             honeypot INTEGER, asn_org TEXT, cloud TEXT, country TEXT, models TEXT);
      DROP TABLE IF EXISTS fofa_model;
      CREATE TABLE fofa_model(host TEXT, name TEXT, param_size TEXT, quant TEXT, publisher TEXT);
    """)
    c.executemany("INSERT OR REPLACE INTO fofa_host VALUES (?,?,?,?,?,?,?,?,?)", best.values())
    for r in best.values():
        for name, ps, q, pub in json.loads(r[8]):
            c.execute("INSERT INTO fofa_model VALUES (?,?,?,?,?)", (r[0], name, ps, q, pub))
    c.execute("CREATE INDEX idx_model_host ON fofa_model(host)")
    c.execute("CREATE INDEX idx_host_mtime ON fofa_host(mtime)")
    con.commit()
    hp = c.execute("SELECT COUNT(*) FROM fofa_host WHERE honeypot=1").fetchone()[0]
    wm = c.execute("SELECT COUNT(*) FROM fofa_host WHERE models!='[]'").fetchone()[0]
    print(f"files={len(files)} empty(no-result)={empty} raw_asset_rows={raw_rows} "
          f"-> unique hosts after dedup={len(best)}  ({raw_rows-len(best)} dupes collapsed)", file=sys.stderr)
    print(f"fofa_host: {len(best)}  with-models: {wm}  honeypot: {hp}", file=sys.stderr)
    for mo, n in c.execute("SELECT substr(mtime,1,7) m, COUNT(*) FROM fofa_host WHERE mtime!='' GROUP BY m ORDER BY m"):
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
