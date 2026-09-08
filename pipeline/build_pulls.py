#!/usr/bin/env python3
"""Compare each official model's share of ollama.com's advertised pull counts
against its share of the models actually found installed on exposed servers.

Both sides are proportions of the same universe - the 239 models on
ollama.com/library - so the absolute mismatch in scale (a billion downloads
against a hundred thousand observed installs) cancels out and what is left is
composition: of everything downloaded, what fraction is llama3.1, and of
everything we found running, what fraction is llama3.1.

The two numbers measure different acts. Pulls are cumulative and global since a
model was published, and count CI jobs, re-pulls after a wipe, and every laptop
that tried a model once. The survey side is a point-in-time census of machines
left exposed to the internet. So a gap is not by itself evidence of anything; it
is the question the chart poses, not its answer.

Because the pull count only ever goes up, the all-models view is dominated by
whatever has been on the library longest, and a recent model cannot rank however
fast it is being adopted. Dividing by the model's age does not fix that - the
library's date is a *last updated* stamp, so for an old model the denominator is
time since it was last re-pushed, which has nothing to do with the window the
pulls accumulated over. The honest fixes are both here instead:

  * a recency cohort, where both sides are renormalised over only the models
    published or refreshed within a window, so recent models are compared with
    each other rather than with a three-year-old default;
  * a true delta, once library_pulls.json holds two or more fetch days, which is
    the only way to measure pulls *now* rather than pulls ever. It appears on
    its own as soon as a second snapshot exists.

Writes site/data/pulls.json."""
import json, pathlib, sqlite3, sys, datetime, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
CACHE = ROOT / "pipeline" / "library_pulls.json"
EXCLUDE_SOURCES = {"ollamaspider"}

_MONTH = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
_UPD = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")


def upd_date(s):
    m = _UPD.match(s or "")
    return (datetime.date(int(m.group(3)), _MONTH[m.group(1)], int(m.group(2)))
            if m else None)


def main():
    if not CACHE.exists():
        print("  library_pulls.json absent; run library_pulls.py first", file=sys.stderr)
        return 1
    hist = json.loads(CACHE.read_text())
    day = max(hist)
    lib = hist[day]

    con = sqlite3.connect(ROOT / "survey.db")
    sources = {i: n for i, n in con.execute("SELECT id,name FROM source")
               if n not in EXCLUDE_SOURCES}
    keep = "(" + ",".join(str(i) for i in sources) + ")"

    questionable = {r[0] for r in con.execute("SELECT server_id FROM questionable_server")}
    cloud = {r[0] for r in con.execute("SELECT model_id FROM model_meta WHERE is_cloud=1")}

    # Count distinct servers per library model, once for the whole population and
    # once with Chapter 2's questionable machines removed. The exclusion matters
    # more here than anywhere else on the page: the phantom catalogue is itself
    # made of library models (codellama, llama3, qwen2.5, openchat, deepseek-r1,
    # llama2), so leaving those tens of thousands of machines in would manufacture
    # the exact over-representation this chart is looking for.
    obs, obs_clean = {}, {}
    for base, svid, mid in con.execute(
            f"SELECT m.base, sm.server_id, sm.model_id FROM server_model sm"
            f" JOIN model m ON m.id=sm.model_id WHERE sm.source_id IN {keep}"):
        if mid in cloud or base not in lib:
            continue
        obs.setdefault(base, set()).add(svid)
        if svid not in questionable:
            obs_clean.setdefault(base, set()).add(svid)

    # Age from the real release date (pipeline/model_releases.py), not from
    # ollama.com's last-updated stamp: that stamp dates qwen3.5 and qwen3.6 to
    # the same day when they are six weeks apart, so a recency cohort built on
    # it would be sorting by "recently re-pushed" instead of "recently released".
    today = datetime.date.today()
    rel_path = ROOT / "pipeline" / "model_releases.json"
    released = {}
    if rel_path.exists():
        mr = json.loads(rel_path.read_text())
        released = {n: e["date"] for n, e in mr["models"].items()
                    if e["source"].startswith("catalogue")}
    age, age_src = {}, {}
    for name in lib:
        d = None
        if name in released:
            d = datetime.date.fromisoformat(released[name])
            age_src[name] = "catalogue"
        else:
            d = upd_date(lib[name].get("updated"))
            age_src[name] = "ollama-updated" if d else None
        age[name] = max((today - d).days, 1) if d else None

    # A real rate needs two observations of the counter. Once there are, the
    # delta is pulls that actually happened in a known window.
    days = sorted(hist)
    delta, delta_days = {}, 0
    if len(days) >= 2:
        prev, prev_day = hist[days[-2]], days[-2]
        delta_days = max((datetime.date.fromisoformat(day)
                          - datetime.date.fromisoformat(prev_day)).days, 1)
        for name, m in lib.items():
            if name in prev:
                d = m["pulls"] - prev[name]["pulls"]
                if d >= 0:
                    delta[name] = d

    tot_pulls = sum(m["pulls"] for m in lib.values())
    tot_obs = sum(len(v) for v in obs.values())
    tot_obs_clean = sum(len(v) for v in obs_clean.values())

    rows = []
    for name, m in lib.items():
        n, nc = len(obs.get(name, ())), len(obs_clean.get(name, ()))
        rows.append({
            "name": name,
            "pulls": m["pulls"],
            "tags": m["tags"],
            "updated": m["updated"],
            "age_days": age[name],
            "age_source": age_src.get(name),
            "released": released.get(name),
            "delta_pulls": delta.get(name),
            "pull_share": m["pulls"] / tot_pulls,
            "servers": n,
            "servers_clean": nc,
            "obs_share": n / tot_obs if tot_obs else 0,
            "obs_share_clean": nc / tot_obs_clean if tot_obs_clean else 0,
        })
    rows.sort(key=lambda r: -r["pulls"])

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pulls.json").write_text(json.dumps({
        "fetched": day,
        "n_models": len(rows),
        "total_pulls": tot_pulls,
        "snapshot_days": days,
        "delta_days": delta_days,
        "has_delta": bool(delta),
        "total_servers": tot_obs,
        "total_servers_clean": tot_obs_clean,
        "models": rows,
    }, separators=(",", ":")))

    print(f"  pulls.json     {len(rows)} models  {tot_pulls/1e9:.2f}B pulls vs "
          f"{tot_obs:,} installs ({tot_obs_clean:,} excluding questionable)")
    if delta:
        print(f"  delta available: {len(delta)} models over {delta_days}d "
              f"({days[-2]} -> {days[-1]})")
    else:
        print(f"  delta view: needs a second fetch day (have {len(days)}: "
              f"{', '.join(days)})")
    ncat = sum(1 for r in rows if r["age_source"] == "catalogue")
    print(f"  dates: {ncat} from the release catalogue, "
          f"{len(rows) - ncat} falling back to ollama.com's updated stamp")
    for cut in (365, 180, 90):
        c = [r for r in rows if r["age_days"] and r["age_days"] <= cut and r["servers"]]
        print(f"  cohort <= {cut}d: {len(c):3} models, "
              f"{sum(r['servers'] for r in c):,} installs")
    print(f"  {'model':22} {'pull%':>7} {'obs%':>7} {'ratio':>7}   "
          f"{'obs% cl':>7} {'ratio':>7}")
    for r in rows[:12]:
        rt = r["obs_share"] / r["pull_share"] if r["pull_share"] else 0
        rc = r["obs_share_clean"] / r["pull_share"] if r["pull_share"] else 0
        print(f"  {r['name']:22} {100*r['pull_share']:6.2f}% {100*r['obs_share']:6.2f}%"
              f" {rt:6.2f}x   {100*r['obs_share_clean']:6.2f}% {rc:6.2f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
