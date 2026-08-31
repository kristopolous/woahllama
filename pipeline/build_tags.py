#!/usr/bin/env python3
"""Parse /api/tags probe captures (tmp/graflex/check-<ip>-<ts>.json) into per-model
pull dates. modified_at is the real date a model was pulled onto the host, so the
oldest one is a lower bound on host age. Writes private tables into fofa/fofa.db
(real IPs -> gitignored). :cloud tags are dropped, per the standing rule."""
import os, re, json, glob, sqlite3, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAFLEX = os.path.join(ROOT, "tmp", "graflex")
DB = os.path.join(ROOT, "fofa", "fofa.db")
# check-<ip>-<ts>.json  OR the fixed form check-<ip>-<port>-<ts>.json
FN = re.compile(r'check-([0-9a-fA-F:.]+?)(?:-(\d{1,5}))?-(\d{14})\.json$')
IMPOSSIBLE = {'gpt-4:latest','gpt-4o:latest','claude-3-opus:latest','gpt-3.5-turbo:latest',
              'claude-3.5-sonnet:latest','gpt-4-turbo:latest','gpt-5:latest','verif_sys:latest'}

def mod_ts(s):
    try: return int(datetime.datetime.fromisoformat(s).timestamp())
    except: return None

def probe_ts(s):
    try: return int(datetime.datetime.strptime(s, "%Y%m%d%H%M%S")
                    .replace(tzinfo=datetime.timezone.utc).timestamp())
    except: return None

def main():
    files = (glob.glob(os.path.join(GRAFLEX, "check-*.json"))
             + glob.glob(os.path.join(GRAFLEX, "tags", "check-*.json")))
    con = sqlite3.connect(DB); c = con.cursor()
    c.executescript("""
      DROP TABLE IF EXISTS tags_model;
      CREATE TABLE tags_model(host TEXT, probe_ts INT, name TEXT, modified_ts INT,
                              size INT, param_size TEXT, quant TEXT, family TEXT, digest TEXT);
      DROP TABLE IF EXISTS tags_host;
      CREATE TABLE tags_host(host TEXT PRIMARY KEY, probe_ts INT, n_models INT,
                             oldest_ts INT, newest_ts INT, responder INT, empty INT);
    """)
    mrows, hrows = [], []
    empties = responders = with_dates = 0
    for f in files:
        try: d = json.load(open(f))
        except: continue
        if not isinstance(d, dict): continue
        # new format: {host:"ip:port", check_time: <unix>, payload:{models:[...]}}
        if d.get("host") and "payload" in d:
            host = d["host"]
            pts = int(d["check_time"]) if d.get("check_time") else None
            models = (d.get("payload") or {}).get("models") or []
        else:
            # legacy: check-<ip>[-<port>]-<ts>.json with top-level models
            m = FN.search(os.path.basename(f))
            if not m: continue
            ip, port, pts_s = m.group(1), m.group(2), m.group(3)
            pts = probe_ts(pts_s)
            host = f"{ip}:{port}" if port else ip
            models = d.get("models") or []
        # drop :cloud
        models = [x for x in models if not (x.get("name","").endswith(":cloud"))]
        if not models:
            empties += 1
            hrows.append((host, pts, 0, None, None, 0, 1)); continue
        mts = []
        digs = set(); imp = False
        for x in models:
            det = x.get("details") or {}
            t = mod_ts(x.get("modified_at",""))
            if t: mts.append(t)
            digs.add(x.get("digest"))
            if x.get("name") in IMPOSSIBLE: imp = True
            mrows.append((host, pts, x.get("name"), t, x.get("size"),
                          det.get("parameter_size"), det.get("quantization_level"),
                          det.get("family"), x.get("digest")))
        # responder: reports an impossible model, or many "different" names on one tiny shared blob
        shared = len(models) >= 3 and len(digs) == 1
        resp = 1 if (imp or shared) else 0
        responders += resp
        if mts: with_dates += 1
        hrows.append((host, pts, len(models), (min(mts) if mts else None),
                      (max(mts) if mts else None), resp, 0))
    c.executemany("INSERT INTO tags_model VALUES (?,?,?,?,?,?,?,?,?)", mrows)
    c.executemany("INSERT OR REPLACE INTO tags_host VALUES (?,?,?,?,?,?,?)", hrows)
    con.commit()
    # ---- summary ----
    def fmtd(ts): return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%d') if ts else '-'
    print(f"files={len(files)}  hosts={len(hrows)}  empty={empties}  responders={responders}  model_rows={len(mrows)}")
    rng = c.execute("SELECT min(modified_ts), max(modified_ts) FROM tags_model WHERE modified_ts IS NOT NULL").fetchone()
    print(f"modified_at range: {fmtd(rng[0])} -> {fmtd(rng[1])}")
    print("\nhost age (probe_ts - oldest modified_at), non-responder hosts with dates:")
    ages = []
    for pts, old in c.execute("SELECT probe_ts, oldest_ts FROM tags_host WHERE responder=0 AND oldest_ts IS NOT NULL AND empty=0"):
        ages.append((pts - old)//86400)
    ages.sort()
    if ages:
        import statistics
        print(f"  n={len(ages)}  median={statistics.median(ages):.0f}d  max={max(ages)}d  "
              f"(={max(ages)/365:.1f}y)  >180d: {sum(1 for a in ages if a>180)}  >365d: {sum(1 for a in ages if a>365)}")
    print("\nmodels pulled per month (all hosts, real arrival dates):")
    import collections
    mo = collections.Counter()
    for (t,) in c.execute("SELECT modified_ts FROM tags_model WHERE modified_ts IS NOT NULL"):
        mo[datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m')] += 1
    for k in sorted(mo): print(f"   {k}: {mo[k]}")
    con.close()

if __name__ == "__main__":
    main()

def build_site_aggregate():
    """Comparative aggregate for the mystery-section chart: per-host median genuine
    model size, fake-carrying vs clean cohorts. Shares only, no addresses."""
    import re, json, statistics, collections, os, sqlite3
    con = sqlite3.connect(DB); c = con.cursor()
    IMP = re.compile(r'^(gpt-?[345]|gpt-4o|o[134]\b|chatgpt|claude|gemini|grok|dall-?e)', re.I)
    hm = collections.defaultdict(list)
    for host, name, size in c.execute("SELECT host,name,size FROM tags_model WHERE size>0"):
        hm[host].append((name, size))
    EDGES = [0, .5, 1, 2, 4, 8, 16, 1e9]     # GB bucket edges
    LABELS = ["<0.5", "0.5–1", "1–2", "2–4", "4–8", "8–16", "16+"]
    fake = collections.Counter(); clean = collections.Counter()
    fake_meds = []; clean_meds = []
    for h, ms in hm.items():
        has_fake = any(IMP.match(n) for n, _ in ms)
        gen = [s/1e9 for n, s in ms if not IMP.match(n)]
        if not gen: continue
        med = statistics.median(gen)
        b = next(i for i in range(len(EDGES)-1) if EDGES[i] <= med < EDGES[i+1])
        (fake if has_fake else clean)[b] += 1
        (fake_meds if has_fake else clean_meds).append(med)
    fn, cn = len(fake_meds), len(clean_meds)
    out = {
        "buckets": LABELS,
        "fake":  [round(100*fake[i]/fn, 1) for i in range(len(LABELS))],
        "clean": [round(100*clean[i]/cn, 1) for i in range(len(LABELS))],
        "fake_n": fn, "clean_n": cn,
        "fake_median": round(statistics.median(fake_meds), 2),
        "clean_median": round(statistics.median(clean_meds), 2),
        "fake_sub1": round(100*sum(1 for x in fake_meds if x < 1)/fn),
        "clean_sub1": round(100*sum(1 for x in clean_meds if x < 1)/cn),
    }
    p = os.path.join(ROOT, "site", "data", "fake_size.json")
    json.dump(out, open(p, "w"))
    print(f"wrote {p}: fake median {out['fake_median']}GB vs clean {out['clean_median']}GB")
    con.close()

if __name__ == "__main__":
    build_site_aggregate()
