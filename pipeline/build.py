"""Turn survey.db into compact JSON for the static site.

Series are emitted as arrays indexed by day since day0 rather than objects per
day, which roughly halves the payload before gzip.  Every population series
comes in two variants:

  all    - every server the scanners reported
  clean  - identical-catalogue clusters removed (see clusters.py)

Both ship because the gap between them is itself a finding: ~31% of all servers
ever recorded share a single honeypot fingerprint.
"""
import collections, datetime, gzip, json, pathlib, sqlite3
from mask import mask_host
from vendors import vendor as vendor_of

ROOT = pathlib.Path(__file__).resolve().parent.parent
# OllamaSpider is excluded: only 15.6% of the servers it reports sit on Ollama's
# port (vs ~47% for the other two), it spreads over 7,911 ports including
# CouchDB's 5984 and Consul's 8500, and 49% of its servers fall in blocks that
# report an identical model list which then changes in lockstep - it is scanning
# an undifferentiated Shodan dump, not verified Ollama hosts.
EXCLUDE_SOURCES = {"ollamaspider"}
OUT = ROOT / "site" / "data"
DAY = 86400
TOP_MODELS = 100


def write(path, obj):
    raw = json.dumps(obj, separators=(",", ":")).encode()
    path.write_bytes(raw)
    print(f"  {path.name:16} {len(raw)/1e6:7.2f} MB  "
          f"({len(gzip.compress(raw, 6))/1e6:.2f} MB gzipped)")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ROOT / "survey.db")
    lo, hi = con.execute("SELECT min(start_ts), max(end_ts) FROM presence").fetchone()
    d0 = lo - lo % DAY
    # drop the most recent CUTOFF_DAYS: the latest day or two of scanning is often
    # partial, and a half-finished day reads as a real drop in every trend chart
    CUTOFF_DAYS = 2
    ndays = (hi - d0) // DAY + 1 - CUTOFF_DAYS
    sources = {i: n for i, n in con.execute("SELECT id,name FROM source")
               if n not in EXCLUDE_SOURCES}
    keep = "(" + ",".join(str(i) for i in sources) + ")"
    print(f"{ndays} days from {d0}")

    sybil = set(con.execute("SELECT server_id, day FROM sybil_day"))

    # `-cloud` tags proxy to Ollama's hosted service: no weights on the machine,
    # no disk, no GPU. They are not a deployment, so they are dropped from every
    # model-level count rather than carried with a caveat.
    cloud = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE is_cloud=1")}
    print(f"  dropping {len(cloud)} cloud-proxied model names")

    def days(a, b):
        return range(max(a, 0), min(b, ndays - 1) + 1)

    # ---- 1. population ------------------------------------------------------
    # sets, not counters: a server that flaps twice within one day is still
    # one exposed server that day
    per_src = {s: [set() for _ in range(ndays)] for s in sources}
    per_src_clean = {s: [set() for _ in range(ndays)] for s in sources}
    union = [set() for _ in range(ndays)]
    clean = [set() for _ in range(ndays)]
    for sid, svid, a, b in con.execute(
            f"SELECT source_id,server_id,(start_ts-?)/?,(end_ts-?)/? FROM presence"
            f" WHERE source_id IN {keep}",
            (d0, DAY, d0, DAY)):
        for d in days(a, b):
            per_src[sid][d].add(svid)
            union[d].add(svid)
            if (svid, d) not in sybil:
                per_src_clean[sid][d].add(svid)
                clean[d].add(svid)
    write(OUT/"counts.json", {
        "day0": d0, "ndays": ndays,
        "sources": {sources[s]: [len(x) for x in v] for s, v in per_src.items()},
        "sources_clean": {sources[s]: [len(x) for x in v] for s, v in per_src_clean.items()},
        "union": [len(u) for u in union],
        "clean": [len(c) for c in clean],
        "decoy": [len(u)-len(c) for u, c in zip(union, clean)],
    })

    # ---- 2 & 3. model and vendor popularity --------------------------------
    meta = {i: (b, v) for i, b, v in con.execute(
        "SELECT m.id, m.base, mv.vendor FROM model m"
        " JOIN model_vendor mv ON mv.model_id=m.id")}
    ser = {k: collections.defaultdict(lambda: [0]*ndays)
           for k in ("model_all", "model_clean", "vendor_all", "vendor_clean")}
    seen = collections.defaultdict(set)
    for svid, mid, a, b in con.execute(
            f"SELECT server_id,model_id,(start_ts-?)/?,(end_ts-?)/? FROM server_model"
            f" WHERE source_id IN {keep}",
            (d0, DAY, d0, DAY)):
        if mid in cloud:
            continue
        base, vend = meta[mid]
        for d in days(a, b):
            dirty = (svid, d) in sybil
            for key, name in (("model", base), ("vendor", vend)):
                k = (key, name, d)
                if svid not in seen[k]:
                    seen[k].add(svid)
                    ser[f"{key}_all"][name][d] += 1
                    if not dirty:
                        ser[f"{key}_clean"][name][d] += 1
    top = sorted(ser["model_clean"], key=lambda m: max(ser["model_clean"][m]),
                 reverse=True)[:TOP_MODELS]
    write(OUT/"models.json", {"day0": d0, "ndays": ndays,
                              "all": {m: ser["model_all"][m] for m in top},
                              "clean": {m: ser["model_clean"][m] for m in top},
                              "vendor": {m: vendor_of(m) for m in top}})
    write(OUT/"vendors.json", {"day0": d0, "ndays": ndays,
                               "all": dict(ser["vendor_all"]),
                               "clean": dict(ser["vendor_clean"])})
    del seen

    # ---- 4. country --------------------------------------------------------
    geo = dict(con.execute("SELECT server_id, country FROM server_geo"))
    cser = {"all": collections.defaultdict(lambda: [0]*ndays),
            "clean": collections.defaultdict(lambda: [0]*ndays)}
    for svid, a, b in con.execute(
            f"SELECT DISTINCT server_id,(start_ts-?)/?,(end_ts-?)/? FROM presence"
            f" WHERE source_id IN {keep}",
            (d0, DAY, d0, DAY)):
        cc = geo.get(svid)
        if not cc:
            continue
        for d in days(a, b):
            cser["all"][cc][d] += 1
            if (svid, d) not in sybil:
                cser["clean"][cc][d] += 1
    write(OUT/"geo.json", {"day0": d0, "ndays": ndays,
                           "all": dict(cser["all"]), "clean": dict(cser["clean"])})

    # ---- 4b. country x month, by what the servers are running ------------
    # Counted in model *installs* (server x model), not servers: composition is
    # the question here, and a server running eight models says more about a
    # country's mix than a server running one.  The headline axis is where the
    # lab that trained each model is based - that varies by country and moves
    # over time, where every raw magnitude just redraws the population map.
    from vendors import is_uncensored, origin
    MIN_N = 8
    unc_ids = {i for i, n in con.execute("SELECT id,name FROM model") if is_uncensored(n)}
    big_ids = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE params_b >= 30 AND is_cloud=0")}
    sized_ids = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE params_b IS NOT NULL AND is_cloud=0")}
    lowq_ids = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE is_cloud=0"
        " AND quant_class IN ('q2','q3','q4','iq2','iq3')")}
    quantknown_ids = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE quant_class IS NOT NULL AND is_cloud=0")}
    vend_of = dict(con.execute("SELECT model_id, vendor FROM model_vendor"))
    orig_of = {m: origin(v) for m, v in vend_of.items()}
    # Weekly buckets, not monthly. The frame step and the smoothing window are
    # independent: the page sums a wide window around each frame, so a finer step
    # buys smoother animation without thinning the sample behind any one frame.
    NM = ndays // 7
    day_month = [min(d // 7, NM - 1) for d in range(ndays)]
    months = [datetime.datetime.fromtimestamp(d0 + w*7*DAY, datetime.UTC)
              .strftime("%Y-%m-%d") for w in range(NM)]

    top_vendors = sorted(ser["vendor_clean"],
                         key=lambda v: max(ser["vendor_clean"][v]), reverse=True)[:8]
    tv = set(top_vendors)

    # city geolocation for the by-city view (aggregated to 0.1 degrees)
    cgeo = {}
    for sid, city, cc2, lat, lon in con.execute(
            "SELECT server_id,city,country,lat,lon FROM server_geo"
            " WHERE lat IS NOT NULL AND lat <> 0"):
        cgeo[sid] = ((round(lat, 1), round(lon, 1)), city, cc2)

    srv = collections.defaultdict(set)                    # (cc,m) -> servers
    csrv = collections.defaultdict(set)                   # (citykey,m) -> servers
    cinst = collections.Counter(); cunc = collections.Counter()
    cbig = collections.Counter(); csized = collections.Counter()
    clowq = collections.Counter(); cqknown = collections.Counter()
    corg = collections.Counter(); cven = collections.Counter()
    cnames = {}
    inst = collections.Counter()                          # (cc,m) -> installs
    big = collections.Counter()                           # installs >= 30B
    sized = collections.Counter()                         # installs with a known size
    lowq = collections.Counter()                          # 4-bit or coarser
    qknown = collections.Counter()
    org = collections.Counter()                           # (cc,m,origin)
    unc = collections.Counter()                           # (cc,m)
    ven = collections.Counter()                           # (cc,m,vendor)
    for svid, a, b in con.execute(
            f"SELECT DISTINCT server_id,(start_ts-?)/?,(end_ts-?)/? FROM presence"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        cc = geo.get(svid)
        cg = cgeo.get(svid)
        for d in days(a, b):
            m = day_month[d]
            if cc:
                srv[(cc, m)].add(svid)
            if cg:
                csrv[(cg[0], m)].add(svid); cnames[cg[0]] = (cg[1], cg[2])
    # one install counted once per country-month, however many days it spans
    seen_inst = set()
    for svid, mid, a, b in con.execute(
            f"SELECT server_id,model_id,(start_ts-?)/?,(end_ts-?)/? FROM server_model"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        cc = geo.get(svid)
        cg = cgeo.get(svid)
        if not cc and not cg:
            continue
        if mid in cloud:
            continue
        vd, og, hot = vend_of.get(mid), orig_of.get(mid, "other"), mid in unc_ids
        for d in days(a, b):
            m = day_month[d]
            k = (svid, mid, m)
            if k in seen_inst:
                continue
            seen_inst.add(k)
            inst[(cc, m)] += 1
            org[(cc, m, og)] += 1
            ck = cg[0] if cg else None
            if ck is not None:
                cinst[(ck, m)] += 1; corg[(ck, m, og)] += 1
            if mid in sized_ids:
                sized[(cc, m)] += 1
                if ck is not None: csized[(ck, m)] += 1
                if mid in big_ids:
                    big[(cc, m)] += 1
                    if ck is not None: cbig[(ck, m)] += 1
            if mid in quantknown_ids:
                qknown[(cc, m)] += 1
                if ck is not None: cqknown[(ck, m)] += 1
                if mid in lowq_ids:
                    lowq[(cc, m)] += 1
                    if ck is not None: clowq[(ck, m)] += 1
            if hot:
                unc[(cc, m)] += 1
                if ck is not None: cunc[(ck, m)] += 1
            if vd in tv:
                ven[(cc, m, vd)] += 1
                if ck is not None: cven[(ck, m, vd)] += 1
    del seen_inst

    countries = {}
    for cc in sorted({k[0] for k in srv}):
        countries[cc] = {
            "srv": [len(srv.get((cc, i), ())) for i in range(NM)],
            "inst": [inst[(cc, i)] for i in range(NM)],
            "unc": [unc[(cc, i)] for i in range(NM)],
            "big": [big[(cc, i)] for i in range(NM)],
            "sized": [sized[(cc, i)] for i in range(NM)],
            "lowq": [lowq[(cc, i)] for i in range(NM)],
            "qknown": [qknown[(cc, i)] for i in range(NM)],
            "o": {o: [org[(cc, i, o)] for i in range(NM)]
                  for o in ("US", "CN", "EU")},
            "v": {v: [ven[(cc, i, v)] for i in range(NM)] for v in top_vendors},
        }
    MIN_CITY = 5
    cities = []
    for ck in {k[0] for k in csrv}:
        n = [len(csrv.get((ck, i), ())) for i in range(NM)]
        if max(n) < MIN_CITY:
            continue
        city, cc2 = cnames[ck]
        cities.append({
            "lat": ck[0], "lon": ck[1], "city": city, "cc": cc2,
            "srv": n,
            "inst": [cinst[(ck, i)] for i in range(NM)],
            "unc": [cunc[(ck, i)] for i in range(NM)],
            "big": [cbig[(ck, i)] for i in range(NM)],
            "sized": [csized[(ck, i)] for i in range(NM)],
            "lowq": [clowq[(ck, i)] for i in range(NM)],
            "qknown": [cqknown[(ck, i)] for i in range(NM)],
            "o": {o: [corg[(ck, i, o)] for i in range(NM)] for o in ("US", "CN", "EU")},
            "v": {v: [cven[(ck, i, v)] for i in range(NM)] for v in top_vendors},
        })
    cities.sort(key=lambda c: -max(c["srv"]))
    write(OUT/"map.json", {"months": months, "min_n": MIN_N, "min_city": MIN_CITY,
                           "vendors": top_vendors, "countries": countries,
                           "cities": cities})


    # ---- 4c. model size and quantisation over time ------------------------
    # Counted in installs, and only over the models whose size or quantisation
    # is actually known - the unresolved remainder is reported alongside rather
    # than silently folded into a band.
    meta = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT model_id, size_band, quant_class, params_b FROM model_meta")}
    from modelmeta import SIZE_BANDS
    BANDS = [b for _, b in SIZE_BANDS]
    band_s = {b: [0]*ndays for b in BANDS}
    quant_s = collections.defaultdict(lambda: [0]*ndays)
    known_sz = [0]*ndays
    known_q = [0]*ndays
    total_i = [0]*ndays
    psum = [0.0]*ndays          # install-weighted mean parameter count
    for svid, mid, a, b in con.execute(
            f"SELECT server_id,model_id,(start_ts-?)/?,(end_ts-?)/? FROM server_model"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        if mid in cloud:
            continue
        band, qc, pb = meta.get(mid, (None, None, None))
        for d in days(a, b):
            total_i[d] += 1
            if band:
                band_s[band][d] += 1
                known_sz[d] += 1
                psum[d] += pb
            if qc:
                quant_s[qc][d] += 1
                known_q[d] += 1
    write(OUT/"sizes.json", {
        "day0": d0, "ndays": ndays,
        "bands": BANDS,
        "band": {b: v for b, v in band_s.items()},
        "quant": dict(quant_s),
        "known_size": known_sz, "known_quant": known_q, "installs": total_i,
        "mean_params": [round(psum[d]/known_sz[d], 2) if known_sz[d] else None
                        for d in range(ndays)],
    })

    # ---- 5. octet frames, weekly, split by vendor -------------------------
    # Weekly rather than daily: 80 frames still animate smoothly, and carrying a
    # per-vendor breakdown on every cell would be 7x the payload at daily.
    oct_of = {r[0]: (r[1], r[2]) for r in
              con.execute("SELECT id,o1,o2 FROM server WHERE ip IS NOT NULL")}
    nweeks = ndays // 7          # whole weeks only: a trailing part-week
                                # plots as a cliff that is just missing days
    tot_w = [collections.defaultdict(set) for _ in range(nweeks)]
    ven_w = [collections.defaultdict(set) for _ in range(nweeks)]   # (cell,vendor)
    for svid, a, b in con.execute(
            f"SELECT DISTINCT server_id,(start_ts-?)/?,(end_ts-?)/? FROM presence"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        cell = oct_of.get(svid)
        if cell is None:
            continue
        for d in days(a, b):
            w = d // 7
            if w < nweeks:
                tot_w[w][cell].add(svid)
    for svid, mid, a, b in con.execute(
            f"SELECT server_id,model_id,(start_ts-?)/?,(end_ts-?)/? FROM server_model"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        cell = oct_of.get(svid)
        vd = vend_of.get(mid)
        if cell is None or vd not in tv or mid in cloud:
            continue
        for d in days(a, b):
            w = d // 7
            if w < nweeks:
                ven_w[w][(cell, vd)].add(svid)

    cells = sorted({c for w in tot_w for c in w})
    idx = {c: i for i, c in enumerate(cells)}
    vlist = top_vendors
    # flat per week: [cellIdx, total, n_vendor0, ... n_vendor7, ...]
    frames = []
    for w in range(nweeks):
        row = []
        for c in sorted(tot_w[w], key=idx.get):
            row.append(idx[c])
            row.append(len(tot_w[w][c]))
            row.extend(len(ven_w[w].get((c, v), ())) for v in vlist)
        frames.append(row)
    write(OUT/"octets.json", {
        "day0": d0, "nweeks": nweeks, "vendors": vlist,
        "cells": [list(c) for c in cells], "frames": frames})
    del tot_w, ven_w

    # ---- 6. lifetimes ------------------------------------------------------
    import bisect
    life = con.execute(
        "SELECT server_id, min(start_ts), max(end_ts), sum(n_snap), count(*),"
        f" count(DISTINCT source_id) FROM presence WHERE source_id IN {keep}"
        " GROUP BY server_id").fetchall()
    dirty_ever = {r[0] for r in con.execute("SELECT DISTINCT server_id FROM sybil_day")}
    urls = dict(con.execute("SELECT id,url FROM server"))
    gc = {r[0]: (r[1], r[2]) for r in
          con.execute("SELECT server_id,country,city FROM server_geo")}
    grid = [0, .25, .5, 1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180,
            240, 300, 365, 450, 560]
    out = {"n": len(life), "end_ts": hi}
    HBUCKETS = [(0, 1, "under a day"), (1, 7, "1–7 days"), (7, 30, "1–4 weeks"),
                (30, 90, "1–3 months"), (90, 180, "3–6 months"),
                (180, 365, "6–12 months"), (365, 1e9, "over a year")]
    for name, rows in (("all", life),
                       ("clean", [r for r in life if r[0] not in dirty_ever])):
        spans = sorted((r[2]-r[1])/DAY for r in rows)
        n = len(spans)
        out[name] = {
            "n": n, "median": spans[n//2], "mean": sum(spans)/n,
            "survival": [[t, (n-bisect.bisect_left(spans, t))/n] for t in grid],
            "still_live": sum(1 for r in rows if r[2] > hi-7*DAY)/n,
            "hist": [[lab, sum(1 for s in spans if lo <= s < hi_)]
                     for lo, hi_, lab in HBUCKETS],
        }
    longest = sorted((r for r in life if r[0] not in dirty_ever),
                     key=lambda r: (-(r[2]-r[1]), -r[3]))[:200]
    out["top"] = [{"url": mask_host(urls[r[0]]), "days": round((r[2]-r[1])/DAY, 1),
                   "obs": r[3], "runs": r[4], "sources": r[5],
                   "cc": gc.get(r[0], (None, None))[0],
                   "city": gc.get(r[0], (None, None))[1]} for r in longest]
    write(OUT/"lifetime.json", out)

    # ---- 7. operator behaviour: /24 blocks as a proxy for one operator -----
    # A single server alone in its /24 is somebody's box; twenty in one /24 that
    # all appear the same hour is somebody orchestrating a fleet.  Concurrent
    # block size is used rather than lifetime size, so a block that grows and
    # shrinks is described by what it was doing on the day in question.
    ip24, live = {}, collections.defaultdict(list)
    for sid, o1, o2, ip in con.execute(
            "SELECT id,o1,o2,ip FROM server WHERE ip IS NOT NULL"):
        ip24[sid] = ".".join(ip.split(".")[:3])
    for svid, a, b in con.execute(
            f"SELECT DISTINCT server_id,(start_ts-?)/?,(end_ts-?)/? FROM presence"
            f" WHERE source_id IN {keep}", (d0, DAY, d0, DAY)):
        if svid in ip24:
            live[svid].append((max(a, 0), min(b, ndays-1)))

    CLASSES = [("lone", 1, 1), ("small (2-4)", 2, 4),
               ("mid (5-19)", 5, 19), ("large (20+)", 20, 10**9)]
    day_block = [collections.defaultdict(set) for _ in range(ndays)]
    for svid, runs in live.items():
        blk = ip24[svid]
        for a, b in runs:
            for d in range(a, b+1):
                day_block[d][blk].add(svid)
    comp = {c[0]: [0]*ndays for c in CLASSES}
    for d, blocks in enumerate(day_block):
        for blk, svs in blocks.items():
            n = len(svs)
            for name, lo, hi in CLASSES:
                if lo <= n <= hi:
                    comp[name][d] += n
                    break

    # one point per block: peak concurrent size vs total span
    blocks = collections.defaultdict(lambda: [0, ndays, -1])   # peak, first, last
    for d, bs in enumerate(day_block):
        for blk, svs in bs.items():
            rec = blocks[blk]
            rec[0] = max(rec[0], len(svs))
            rec[1] = min(rec[1], d)
            rec[2] = max(rec[2], d)
    cc = dict(con.execute("SELECT server_id,country FROM server_geo"))
    blk_cc = {}
    for svid in live:
        blk_cc.setdefault(ip24[svid], cc.get(svid))
    scatter = [[b[0], b[2]-b[1]+1, blk_cc.get(k) or "??", k]
               for k, b in blocks.items()]
    write(OUT/"pools.json", {
        "day0": d0, "ndays": ndays,
        "classes": [c[0] for c in CLASSES],
        "composition": comp,
        "scatter": scatter,
    })

    con.close()


if __name__ == "__main__":
    main()
