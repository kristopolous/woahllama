#!/usr/bin/env python3
"""Parse Shodan search-result HTML (tmp/graflex/shodan-results-*.txt) into
private fofa/fofa.db table shodan_host. Each host = one online liveness sample."""
import os, re, glob, sqlite3
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(ROOT, "tmp", "graflex")
DB = os.path.join(ROOT, "fofa", "fofa.db")
FN = re.compile(r'shodan-results-([A-Za-z0-9]+)-')
BLK = re.compile(r'<div class="result">(.*?)<div class="banner-data">', re.S)
IP  = re.compile(r'/host/([0-9.]+)')
URL = re.compile(r'https?://[0-9.]+:(\d+)')
TS  = re.compile(r'class="timestamp[^"]*"[^>]*>\s*([0-9T:\-]+)')
ORG = re.compile(r'filter-org">([^<]+)')
CITY= re.compile(r'city%3A%22[^"]*"[^>]*>([^<]+)</a>')

def parse(path):
    html = open(path, encoding='utf-8', errors='replace').read()
    fm = FN.search(os.path.basename(path)); country = fm.group(1) if fm else None
    out = []
    for b in BLK.findall(html):
        ip = IP.search(b); ts = TS.search(b); port = URL.search(b)
        if not ip or not ts: continue
        org = ORG.search(b); city = CITY.search(b)
        p = int(port.group(1)) if port else None
        out.append((f"{ip.group(1)}:{p}", ip.group(1), p, ts.group(1).replace('T',' '),
                    (org.group(1).strip() if org else ''), country,
                    (city.group(1).strip() if city else '')))
    return out

def main():
    files = glob.glob(os.path.join(G, "shodan-results-*.txt"))
    best = {}   # host -> row, keep most recent ts
    raw = 0
    for f in files:
        for r in parse(f):
            raw += 1; h = r[0]; cur = best.get(h)
            if cur is None or r[3] > cur[3]: best[h] = r
    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS shodan_host;
      CREATE TABLE shodan_host(host TEXT PRIMARY KEY, ip TEXT, port INTEGER, ts TEXT,
                               org TEXT, country TEXT, city TEXT);
    """)
    c.executemany("INSERT OR REPLACE INTO shodan_host VALUES (?,?,?,?,?,?,?)", best.values())
    c.execute("CREATE INDEX idx_shodan_ipport ON shodan_host(ip,port)")
    con.commit()
    print(f"shodan files={len(files)} raw_rows={raw} unique_hosts={len(best)}")
    # overlap with fofa + probe
    ov_f = c.execute("""SELECT COUNT(*) FROM shodan_host s JOIN fofa_host f
                        ON s.ip=f.ip AND s.port=f.port""").fetchone()[0]
    ov_p = c.execute("""SELECT COUNT(*) FROM shodan_host s JOIN probe p
                        ON s.host=p.host""").fetchone()[0]
    ts_range = c.execute("SELECT MIN(ts), MAX(ts) FROM shodan_host WHERE ts!=''").fetchone()
    print(f"shodan∩fofa (ip:port): {ov_f}   shodan∩probe: {ov_p}")
    print(f"shodan ts range: {ts_range[0]}  ..  {ts_range[1]}")
    con.close()

if __name__ == "__main__":
    main()
