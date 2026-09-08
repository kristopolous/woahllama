#!/usr/bin/env python3
"""Fill in country for servers the db-ip lookup cannot place, using the country
the capture itself reported.

geo.py resolves an IP to continent/country/city/lat/lon from the db-ip city-lite
CSV, which is not in the repo, so anything scanned since the last time that file
was present is unplaced. The map and the country charts then thin out at exactly
the recent end, which reads as servers disappearing rather than as missing
geolocation.

Both newer sources carry a country of their own: FOFA reports one per asset, and
the daily live probe records country/ASN alongside the version. Those are used
here to fill country only. Nothing invents a city or a lat/lon, so a host placed
this way appears in the country mix and the choropleth and stays off the city
bubble layer, which is the honest resolution of what the capture actually says.

Never overwrites a db-ip placement: an existing row wins, and this only inserts
countries for servers that have none."""
import os, sqlite3, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVEY = os.path.join(ROOT, "survey.db")
FOFA = os.path.join(ROOT, "fofa", "fofa.db")

# db-ip country codes are two-letter; the capture sources use the same
CONTINENT = {}   # left empty: continent is derived downstream from country


def main():
    if not os.path.exists(FOFA):
        print("  fofa.db absent; skipping capture-based geo fill", file=sys.stderr)
        return 0
    con = sqlite3.connect(SURVEY)
    con.executescript("""
      CREATE TABLE IF NOT EXISTS server_geo(
        server_id INTEGER PRIMARY KEY, continent TEXT, country TEXT,
        stateprov TEXT, city TEXT, lat REAL, lon REAL);
      CREATE INDEX IF NOT EXISTS server_geo_country ON server_geo(country);
    """)
    fc = sqlite3.connect(FOFA)

    url2id = {u: i for i, u in con.execute("SELECT id,url FROM server")}
    placed = {r[0] for r in con.execute(
        "SELECT server_id FROM server_geo WHERE country IS NOT NULL AND country != ''")}

    add = {}
    tables = {r[0] for r in fc.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "fofa_sighting" in tables:
        for ip, port, cc in fc.execute(
                "SELECT ip,port,country FROM fofa_sighting"
                " WHERE country IS NOT NULL AND country != ''"):
            i = url2id.get(f"http://{ip}:{port}")
            if i and i not in placed:
                add[i] = cc
    if "daily_probe" in tables:
        # the probe's own geo lookup is per host and more recent, so it wins a
        # tie with FOFA's country for the same server
        for host, cc in fc.execute(
                "SELECT host,country FROM daily_probe WHERE service='ollama'"
                " AND country IS NOT NULL AND country != ''"):
            i = url2id.get("http://" + host)
            if i and i not in placed:
                add[i] = cc

    con.executemany(
        "INSERT OR IGNORE INTO server_geo(server_id,continent,country,stateprov,"
        "city,lat,lon) VALUES(?,NULL,?,NULL,NULL,NULL,NULL)",
        [(i, cc) for i, cc in add.items()])
    con.commit()
    have, tot = con.execute(
        "SELECT (SELECT COUNT(*) FROM server_geo WHERE country IS NOT NULL AND country!=''),"
        " (SELECT COUNT(*) FROM server)").fetchone()
    withxy = con.execute("SELECT COUNT(*) FROM server_geo WHERE lat IS NOT NULL"
                         " AND lat <> 0").fetchone()[0]
    print(f"  geo fill: +{len(add):,} countries from captures -> "
          f"{have:,}/{tot:,} servers with a country ({100*have/tot:.0f}%), "
          f"{withxy:,} with coordinates")
    con.close(); fc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
