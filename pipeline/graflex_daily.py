#!/usr/bin/env python3
"""Parse the daily graflex live-probe surveys (graflex/*.json) into a private
table in fofa/fofa.db, retained per probe date so repeat runs accumulate instead
of overwriting each other.

Each file is a snapshot of the scanner's cache: it holds the hosts confirmed live
on that run plus stale carry-over rows from earlier runs, each stamped with its
own `checked` time. So the file name is not the observation date - `checked` is.
Deduplicating the union on (service, host, probe day) turns the five files into
one set of dated online sightings.

The surveys cover several inference servers, not just Ollama; the service is kept
so the Ollama subset can be selected downstream. Real IPs -> gitignored."""
import os, json, glob, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "graflex")
DB = os.path.join(ROOT, "fofa", "fofa.db")


def host_port(url):
    """graflex records the endpoint as a URL; the rest of the pipeline keys on
    host:port, with the scheme's default port filled in when it is implicit."""
    u = (url or "").strip()
    scheme, _, rest = u.partition("://")
    if not rest:
        scheme, rest = "http", u
    rest = rest.split("/")[0]
    if ":" in rest and not rest.endswith(":"):
        h, _, p = rest.rpartition(":")
        if p.isdigit():
            return h, int(p)
    return rest.rstrip(":"), 443 if scheme == "https" else 80


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.json")))
    if not files:
        print("  graflex/ daily surveys absent (private); skipping", file=sys.stderr)
        return
    best = {}   # (service, host:port, day) -> row, keeping the latest check
    for f in files:
        try:
            rows = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  skip {os.path.basename(f)}: {e}", file=sys.stderr)
            continue
        for o in rows:
            svc = o.get("service") or ""
            ck = o.get("checked") or ""
            if not svc or len(ck) < 10:
                continue
            h, port = host_port(o.get("url"))
            if not h or not port:
                continue
            hp, day = f"{h}:{port}", ck[:10]
            k = (svc, hp, day)
            models = json.dumps(sorted(set(o.get("models") or [])))
            cur = best.get(k)
            if cur is None or ck > cur[4]:
                best[k] = (svc, hp, port, day, ck, o.get("url") or "", models)

    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS daily_probe;
      CREATE TABLE daily_probe(service TEXT, host TEXT, port INTEGER, day TEXT,
                               checked TEXT, url TEXT, models TEXT,
                               PRIMARY KEY(service, host, day));
    """)
    c.executemany("INSERT OR REPLACE INTO daily_probe VALUES (?,?,?,?,?,?,?)", best.values())
    c.execute("CREATE INDEX idx_daily_day ON daily_probe(day)")
    con.commit()
    print(f"daily_probe: {len(files)} files -> {len(best)} dated sightings", file=sys.stderr)
    for svc, n, hosts, d0, d1 in c.execute(
            "SELECT service, COUNT(*), COUNT(DISTINCT host), MIN(day), MAX(day)"
            " FROM daily_probe GROUP BY service ORDER BY 3 DESC"):
        print(f"   {svc:10} {hosts:5} hosts  {n:5} sightings  {d0}..{d1}", file=sys.stderr)
    print("   ollama probe days: " + ", ".join(
        f"{d}={n}" for d, n in c.execute(
            "SELECT day, COUNT(*) FROM daily_probe WHERE service='ollama'"
            " GROUP BY day ORDER BY day")), file=sys.stderr)
    con.close()


if __name__ == "__main__":
    main()
