#!/usr/bin/env python3
"""Cross-correlate the Ollama release a host is running against the age of the
models it is serving.

You generally have to update Ollama to run a newly published model: new
architectures land in the daemon first. So a host running a daemon released in,
say, March that is serving a model published the following February is doing
something deliberate - somebody pulled that model onto that machine after the
daemon was already old. Either the operator is maintaining the box, or something
else is putting new models on it.

Two dates go into this:

  daemon  the release date of the version the host reports, from the tag history
          in the `ollama/` clone (pipeline/ollama_releases.py). Exact.
  model   the release date from pipeline/model_releases.py, which reads the
          Artificial Analysis catalogue. NOT ollama.com's date: that is a
          last-updated stamp, wrong by months, and it puts qwen3.5 and qwen3.6
          on the same day when they are six weeks apart.

Only models the catalogue actually dates are charted. The fallback date for
everything else is derived from when hosts were seen to have pulled the model,
which cannot be compared against host daemon dates without arguing in a circle.

Scope: only hosts from the daily live probe, because that is the only source
that reports a daemon version at all. It is roughly two thousand machines, not
the whole survey, and the chart says so.

Writes site/data/lag.json."""
import json, pathlib, sqlite3, sys, datetime, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
FOFA = ROOT / "fofa" / "fofa.db"
RELEASES = ROOT / "pipeline" / "ollama_releases.json"
RELEASES_M = ROOT / "pipeline" / "model_releases.json"

DAY = 86400
_MONTH = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_UPD = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")


def upd_date(s):
    m = _UPD.match(s or "")
    if not m:
        return None
    return datetime.date(int(m.group(3)), _MONTH[m.group(1)], int(m.group(2)))


def iso(s):
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def main():
    for p in (RELEASES, RELEASES_M):
        if not p.exists():
            print(f"  {p.name} absent; run its builder first", file=sys.stderr)
            return 1
    releases = {v: iso(d) for v, d in
                json.loads(RELEASES.read_text())["releases"].items()}
    mr = json.loads(RELEASES_M.read_text())
    # A `first-seen` date is inferred from when hosts pulled the model, so
    # setting it against those same hosts' daemon dates would be circular.
    # Catalogue-dated models only.
    tagdate = {n: iso(e["date"]) for n, e in mr["tags"].items()
               if e["source"].startswith("catalogue")}
    mdate = {n: iso(e["date"]) for n, e in mr["models"].items()
             if e["source"].startswith("catalogue")}

    # Chapter 2's fakes are in the catalogue because it covers closed models
    # too, and a `gpt-4:latest` blob on an Ollama host is not OpenAI shipping
    # weights. `-cloud` tags proxy to a hosted service and commit nothing to the
    # machine. Neither says anything about what that daemon can run.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from questionable import IMPOSSIBLE_RE, IMPOSSIBLE_NAMES

    def usable(name):
        if not name or name.endswith("-cloud") or "-cloud" in name.split(":")[-1]:
            return False
        if IMPOSSIBLE_RE.match(name) or name.split(":")[0].lower() in IMPOSSIBLE_NAMES:
            return False
        return True

    def date_of(name):
        """Tag-specific date when the catalogue names that variant, else the
        line's first release."""
        if not usable(name):
            return None
        return tagdate.get(name) or mdate.get(name.split(":")[0])

    con = sqlite3.connect(FOFA)
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                       " AND name='daily_probe'").fetchone():
        print("  daily_probe absent; run graflex_daily.py first", file=sys.stderr)
        return 1

    # latest sighting per host, so a host counts once with its most recent
    # daemon version and catalogue
    latest = {}
    for host, ck, ver, models in con.execute(
            "SELECT host, checked, version, models FROM daily_probe"
            " WHERE service='ollama' ORDER BY checked"):
        latest[host] = (ck, ver, models)

    hosts, unmatched_ver, no_model = [], 0, 0
    for host, (ck, ver, models) in latest.items():
        rd = releases.get(ver or "")
        if rd is None:
            unmatched_ver += 1
            continue
        names = [n for n in json.loads(models or "[]") if n]
        dated = [(n, date_of(n)) for n in names]
        dated = [(n, d) for n, d in dated if d]
        if not dated:
            no_model += 1
            continue
        # the newest model on the box is what dates the operator's last pull
        newest_name, newest = max(dated, key=lambda t: t[1])
        hosts.append({
            "version": ver,
            "daemon": rd.isoformat(),
            "newest_model": newest_name,
            "newest_model_date": newest.isoformat(),
            "lag_days": (newest - rd).days,
            "n_models": len(names),
            "n_dated": len(dated),
        })

    if not hosts:
        print("  no hosts with both a release date and a dated model", file=sys.stderr)
        return 1

    lags = sorted(h["lag_days"] for h in hosts)
    q = lambda p: lags[min(len(lags) - 1, int(len(lags) * p))]

    # Buckets in months. Negative means the daemon is newer than everything it
    # serves, which is the ordinary case for a machine installed and left alone.
    EDGES = [-10**6, -180, -90, 0, 90, 180, 365, 547, 10**6]
    LABELS = ["daemon 6mo+ newer", "3-6mo newer", "0-3mo newer",
              "model 0-3mo newer", "3-6mo", "6-12mo", "12-18mo", "18mo+"]
    buckets = [0] * len(LABELS)
    for h in hosts:
        for i in range(len(LABELS)):
            if EDGES[i] <= h["lag_days"] < EDGES[i + 1]:
                buckets[i] += 1
                break

    # the tail worth talking about: a model published a year or more after the
    # daemon that is serving it
    notable = sorted((h for h in hosts if h["lag_days"] >= 365),
                     key=lambda h: -h["lag_days"])
    by_ver = {}
    for h in notable:
        by_ver.setdefault(h["version"], 0)
        by_ver[h["version"]] += 1

    # ---- the matrix: one row per model, daemon release dates along x ---------
    # For a given model, which vintages of Ollama are serving it? A circle sits
    # at each month of daemon release, sized by how many hosts. The model's own
    # publication date is marked on the same axis, so circles to the left of the
    # marker are daemons that predate the model they are running.
    # Ranking rows purely by installed base buries every recent release behind
    # models that have had years to accumulate hosts - qwen3.8 sits at rank 24
    # on host count while being one of the newest things anyone is running. So
    # the newest releases that clear a floor get guaranteed slots, and the rest
    # of the rows go to the biggest populations.
    ROWS, RECENT_SLOTS, MIN_HOSTS, MONTH = 22, 8, 20, "%Y-%m"
    pair_hosts = {}            # model -> {daemon_month: n_hosts}
    model_total = {}
    for host, (ck, ver, models) in latest.items():
        rd = releases.get(ver or "")
        if rd is None:
            continue
        dm = rd.strftime(MONTH)
        for n in json.loads(models or "[]"):
            # rows are the tagged name, not the base: qwen3.6:27b shipped on
            # 2026-04-22 and qwen3.6:35b on 2026-04-16, and collapsing them
            # would date both to whichever variant came first
            if date_of(n) is None:
                continue
            d = pair_hosts.setdefault(n, {})
            d[dm] = d.get(dm, 0) + 1
            model_total[n] = model_total.get(n, 0) + 1

    eligible = [m for m in model_total if model_total[m] >= MIN_HOSTS]
    recent = sorted(eligible, key=lambda m: date_of(m), reverse=True)[:RECENT_SLOTS]
    picked = list(recent)
    for m in sorted(model_total, key=lambda m: -model_total[m]):
        if len(picked) >= ROWS:
            break
        if m not in picked:
            picked.append(m)
    # newest model at the top, so the release markers descend as a staircase and
    # a row whose circles sit left of its own marker stands out against it
    picked.sort(key=lambda m: date_of(m), reverse=True)

    allm = sorted({m for b in picked for m in pair_hosts[b]}
                  | {date_of(b).strftime(MONTH) for b in picked})
    # a continuous month axis, so gaps in daemon vintages read as gaps
    y0, m0 = (int(x) for x in allm[0].split("-"))
    y1, m1 = (int(x) for x in allm[-1].split("-"))
    months = []
    y, mo = y0, m0
    while (y, mo) <= (y1, m1):
        months.append(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    midx = {m: i for i, m in enumerate(months)}

    matrix = []
    for b in picked:
        cells = sorted(([midx[m], n] for m, n in pair_hosts[b].items() if m in midx),
                       key=lambda c: c[0])
        rm = date_of(b).strftime(MONTH)
        # "daemon older than the model" is the null expectation for anything
        # published recently - a daemon cannot have been released in the six days
        # since. What is not expected is a daemon a *year or more* older than the
        # model it is serving, so that is the number the chart leans on.
        older = sum(n for m, n in pair_hosts[b].items() if m < rm)
        cutoff = (date_of(b) - datetime.timedelta(days=365)).strftime(MONTH)
        older12 = sum(n for m, n in pair_hosts[b].items() if m < cutoff)
        spread = sorted(m for m, n in pair_hosts[b].items() for _ in range(n))
        matrix.append({
            "name": b,
            "released": date_of(b).isoformat(),
            "released_i": midx.get(rm),
            "hosts": model_total[b],
            "older": older,                       # daemons that predate the model
            "older12": older12,                   # by a year or more
            "p10_daemon": spread[len(spread) // 10],
            "med_daemon": spread[len(spread) // 2],
            "cells": cells,
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lag.json").write_text(json.dumps({
        "months": months,
        "matrix": matrix,
        "n_hosts": len(hosts),
        "unmatched_version": unmatched_ver,
        "no_dated_model": no_model,
        "labels": LABELS,
        "buckets": buckets,
        "median_lag": q(.50),
        "p10": q(.10), "p90": q(.90),
        "n_notable": len(notable),
        "notable_share": len(notable) / len(hosts),
        "notable_versions": sorted(by_ver.items(), key=lambda kv: -kv[1])[:8],
        # a scatter of daemon date against newest-model date, which is where the
        # diagonal makes the "model newer than the daemon" region obvious
        "scatter": [[h["daemon"], h["newest_model_date"], h["lag_days"]]
                    for h in hosts],
        "top_notable": notable[:20],
    }, separators=(",", ":")))

    print(f"  lag.json       {len(hosts)} hosts with a dated daemon and model "
          f"({unmatched_ver} unmatched version, {no_model} no dated model)")
    print(f"  median lag {q(.50)}d   10th {q(.10)}d   90th {q(.90)}d")
    print(f"  {len(notable)} hosts ({100*len(notable)/len(hosts):.0f}%) serve a model "
          f"published 12+ months after their daemon shipped")
    for lab, n in zip(LABELS, buckets):
        print(f"    {lab:20} {n:5}")
    print(f"  matrix: {len(matrix)} models x {len(months)} months")
    for r in matrix[:6]:
        print(f"    {r['name']:22} rel {r['released']}  {r['hosts']:5} hosts  "
              f"median daemon {r['med_daemon']}  p10 {r['p10_daemon']}  "
              f"{r['older12']:4} ({100*r['older12']/r['hosts']:3.0f}%) a year+ older")
    return 0


if __name__ == "__main__":
    sys.exit(main())
