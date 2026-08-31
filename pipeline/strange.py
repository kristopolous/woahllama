"""Characterise the servers that are not what they claim to be.

This is the one part of the survey that uses all three feeds, OllamaSpider
included: its indiscriminate scanning is what makes the anomalies visible.

Four things are separable from the committed data alone, without touching any
of these machines:

  phantom   thousands of addresses reporting one identical model list that then
            changes across all of them at once
  port      only a quarter of "Ollama servers" answer on Ollama's port; the rest
            sit on ports assigned to CouchDB, Consul, MySQL, WinRM
  invented  a model whose reported byte size does not match the real size of the
            tag it names, per ollama.com
  hoarder   the opposite extreme - real machines with enormous local catalogues
"""
import collections, json, pathlib, sqlite3
from mask import mask_host

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

PORT_NAMES = {
    11434: "Ollama", 11435: "Ollama alt", 80: "HTTP", 443: "HTTPS",
    8080: "HTTP alt", 8000: "HTTP alt", 8081: "HTTP alt",
    5984: "CouchDB", 8500: "Consul", 9306: "MySQL wire protocol",
    3306: "MySQL", 5985: "WinRM", 5986: "WinRM over HTTPS",
    2375: "Docker daemon", 6379: "Redis", 9200: "Elasticsearch",
    27017: "MongoDB", 5432: "PostgreSQL", 8888: "Jupyter",
    7001: "WebLogic", 8123: "ClickHouse", 1234: "LM Studio",
    50000: "SAP / misc", 3000: "dev server", 5000: "Flask / UPnP",
    22: "SSH", 23: "Telnet", 7547: "TR-069 CPE management",
}
PLACEHOLDER = ("probe-nonexistent", "academic_research_probe", "world", "mario",
               "demo", "example", "test", "reflection", "costv1")


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    out = {}

    urls = dict(con.execute("SELECT id, url FROM server"))
    ports = dict(con.execute("SELECT id, port FROM server"))
    geo = {r[0]: r[1] for r in con.execute("SELECT server_id, country FROM server_geo")}
    names = dict(con.execute("SELECT id, name FROM model"))

    # ---- the phantom catalogue ---------------------------------------------
    cat = collections.defaultdict(set)
    for sv, m in con.execute("SELECT server_id, model_id FROM server_model"):
        cat[sv].add(m)
    sig = collections.Counter(frozenset(v) for v in cat.values())
    top_sig, top_n = sig.most_common(1)[0]
    members = {s for s, v in cat.items() if v == top_sig}
    # the near-misses: the same list with one entry missing
    near = {s for s, v in cat.items()
            if v != top_sig and v < top_sig and len(v) >= len(top_sig) - 2}
    fleet = members | near
    # the byte sizes reported for the catalogue's models: a real fleet pulls at
    # different times and quantisations and varies; a template reports one number
    size_fp = []
    for m in sorted(top_sig, key=lambda m: names[m]):
        rows = con.execute(
            "SELECT max_bytes, count(*) FROM reported_size WHERE model_id=? GROUP BY max_bytes",
            (m,)).fetchall()
        tot = sum(c for _, c in rows)
        if not tot:
            continue
        top_b, tn = max(rows, key=lambda r: r[1])
        size_fp.append([names[m], top_b, tot, len(rows), round(100*tn/tot, 1)])
    size_fp.sort(key=lambda r: -r[4])

    out["phantom"] = {
        "catalogue": sorted(names[m] for m in top_sig),
        "size_fingerprint": size_fp,
        "exact": len(members),
        "near": len(near),
        "total_servers": con.execute("SELECT count(*) FROM server").fetchone()[0],
        "ports": collections.Counter(
            PORT_NAMES.get(ports[s], str(ports[s])) for s in fleet).most_common(10),
        "distinct_ports": len({ports[s] for s in fleet}),
        "countries": collections.Counter(
            geo.get(s) for s in fleet if geo.get(s)).most_common(10),
    }

    # port inflation: one machine answering the fake catalogue on many ports is
    # counted as many "servers". Collapse the fleet to distinct IPs.
    ip_of = dict(con.execute("SELECT id, ip FROM server WHERE ip IS NOT NULL"))
    fleet_ports = collections.Counter(ip_of[s] for s in fleet if s in ip_of)
    # per-snapshot share: the fleet is a churning population, not a standing count,
    # so report what fraction of a live snapshot it is now and how that grew
    import datetime
    snaps = con.execute(
        "SELECT seq, ts FROM snapshot WHERE source_id=3 ORDER BY seq").fetchall()
    def phantom_share(ts):
        c = collections.defaultdict(set)
        for sv, mid in con.execute(
                "SELECT server_id,model_id FROM server_model WHERE source_id=3"
                " AND start_ts<=? AND end_ts>=?", (ts, ts)):
            c[sv].add(mid)
        if not c:
            return 0, 0
        ph = sum(1 for v in c.values()
                 if v == top_sig or (v < top_sig and len(v) >= 4))
        return ph, len(c)
    latest_ts = snaps[-1][1]
    ph_now, tot_now = phantom_share(latest_ts)
    early = [s for s in snaps if datetime.datetime.fromtimestamp(
                s[1], datetime.UTC) < datetime.datetime(2025, 5, 1, tzinfo=datetime.UTC)]
    ph_early, tot_early = phantom_share(early[len(early)//2][1]) if early else (0, 1)
    out["phantom"]["snapshot"] = {
        "now_phantom": ph_now, "now_total": tot_now,
        "now_pct": round(100*ph_now/max(tot_now, 1)),
        "early_pct": round(100*ph_early/max(tot_early, 1)),
        "spider_total_ever": con.execute(
            "SELECT count(DISTINCT server_id) FROM presence WHERE source_id=3").fetchone()[0],
    }

    out["inflation"] = {
        "hostport": sum(fleet_ports.values()),
        "distinct_ip": len(fleet_ports),
        "multi_port_ips": sum(1 for v in fleet_ports.values() if v > 1),
        "max_ports": max(fleet_ports.values()) if fleet_ports else 0,
        "worst": [[mask_host(ip), n] for ip, n in fleet_ports.most_common(6)],
    }

    # ---- ports --------------------------------------------------------------
    rows = con.execute("""SELECT s.port, count(*) FROM server s
        WHERE EXISTS(SELECT 1 FROM presence p WHERE p.server_id=s.id)
        GROUP BY s.port ORDER BY 2 DESC""").fetchall()
    tot = sum(c for _, c in rows)
    out["ports"] = {
        "total": tot,
        "distinct": len(rows),
        "on_ollama": sum(c for p, c in rows if p in (11434, 11435)),
        "top": [[p, c, PORT_NAMES.get(p, "")] for p, c in rows[:24]],
        "foreign": sum(c for p, c in rows
                       if p in PORT_NAMES and PORT_NAMES[p] not in
                       ("Ollama", "Ollama alt", "HTTP", "HTTPS", "HTTP alt")),
    }

    # ---- placeholder model names -------------------------------------------
    ph = []
    for mid, name in names.items():
        low = name.lower()
        if any(low.startswith(p) or low == p for p in PLACEHOLDER):
            n = con.execute(
                "SELECT count(DISTINCT server_id) FROM server_model WHERE model_id=?",
                (mid,)).fetchone()[0]
            if n:
                ph.append([name, n])
    out["placeholder"] = sorted(ph, key=lambda r: -r[1])[:14]

    # ---- weights that do not match the tag they claim ----------------------
    lib = {}
    for model, tag, nbytes in con.execute(
            "SELECT model, tag, bytes FROM library_tag"):
        lib[(model, tag)] = nbytes
    mismatch, checked = [], 0
    for sv, mid, lo, hi in con.execute(
            "SELECT server_id, model_id, min_bytes, max_bytes FROM reported_size"):
        base, tag = con.execute(
            "SELECT base, tag FROM model WHERE id=?", (mid,)).fetchone()
        real = lib.get((base, tag or "latest"))
        if not real or real < 50_000_000:      # skip embeddings and cloud stubs
            continue
        checked += 1
        ratio = hi / real
        if ratio > 2.5 or ratio < 0.4:
            mismatch.append([mask_host(urls[sv]), names[mid], hi, real, round(ratio, 2)])
    mismatch.sort(key=lambda r: -abs(r[4] - 1))
    out["invented"] = {"checked": checked, "n": len(mismatch),
                       "examples": mismatch[:14]}

    # ---- the real ones, at the other extreme -------------------------------
    big = con.execute("""SELECT rs.server_id, count(*), sum(rs.max_bytes)
        FROM reported_size rs GROUP BY rs.server_id
        ORDER BY 3 DESC LIMIT 14""").fetchall()
    out["hoarders"] = [[mask_host(urls[s]), n, tb, geo.get(s)] for s, n, tb in big]

    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(out, separators=(",", ":")).encode()
    (OUT / "strange.json").write_bytes(raw)
    print(f"  strange.json    {len(raw)/1e6:7.3f} MB")
    p = out["ports"]
    print(f"\nports: {p['on_ollama']:,} of {p['total']:,} on Ollama's own port "
          f"({100*p['on_ollama']/p['total']:.0f}%), {p['distinct']:,} distinct ports")
    ph = out["phantom"]
    print(f"phantom: {ph['exact']:,} exact + {ph['near']:,} near-miss of "
          f"{ph['total_servers']:,} servers, across {ph['distinct_ports']} ports")
    print(f"invented: {out['invented']['n']:,} of {out['invented']['checked']:,} "
          f"size-checkable installs disagree with the published blob")
    con.close()


if __name__ == "__main__":
    main()
