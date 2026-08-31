"""Resolve every observed IPv4 address to a location.

Uses the DB-IP city-lite CSV (CC-BY 4.0, attribution required in the UI).  The
ranges are loaded into a sorted list and bisected rather than range-joined in
SQL: 90k lookups against 4M ranges is instant in memory and needs no extra
index on disk.
"""
import bisect, csv, gzip, ipaddress, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "survey.db"

DDL = """
CREATE TABLE IF NOT EXISTS server_geo(
  server_id INTEGER PRIMARY KEY,
  continent TEXT, country TEXT, stateprov TEXT, city TEXT,
  lat REAL, lon REAL
);
CREATE INDEX IF NOT EXISTS server_geo_country ON server_geo(country);
"""


def load_ranges(path):
    starts, rows = [], []
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 8 or ":" in rec[0]:      # skip IPv6
                continue
            try:
                lo = int(ipaddress.IPv4Address(rec[0]))
                hi = int(ipaddress.IPv4Address(rec[1]))
            except ipaddress.AddressValueError:
                continue
            starts.append(lo)
            rows.append((hi, rec[2], rec[3], rec[4], rec[5],
                         float(rec[6] or 0), float(rec[7] or 0)))
    return starts, rows


def main(csv_path):
    starts, rows = load_ranges(csv_path)
    print(f"loaded {len(starts):,} IPv4 ranges", flush=True)

    con = sqlite3.connect(DB)
    con.executescript(DDL)
    todo = con.execute(
        "SELECT id, ip_int FROM server WHERE ip_int IS NOT NULL").fetchall()

    out, misses = [], 0
    for sid, ip_int in todo:
        i = bisect.bisect_right(starts, ip_int) - 1
        if i < 0 or rows[i][0] < ip_int:
            misses += 1
            continue
        hi, cont, cc, prov, city, lat, lon = rows[i]
        out.append((sid, cont, cc, prov or None, city or None, lat, lon))

    con.executemany("INSERT OR REPLACE INTO server_geo VALUES(?,?,?,?,?,?,?)", out)
    con.commit()
    print(f"resolved {len(out):,} of {len(todo):,} servers ({misses} unmatched)")
    for cc, n in con.execute(
            "SELECT country, count(*) c FROM server_geo GROUP BY country"
            " ORDER BY c DESC LIMIT 15"):
        print(f"  {cc}  {n:6}")
    con.close()


if __name__ == "__main__":
    main(sys.argv[1])
