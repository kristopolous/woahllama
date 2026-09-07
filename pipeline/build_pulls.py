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

Writes site/data/pulls.json."""
import json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
CACHE = ROOT / "pipeline" / "library_pulls.json"
EXCLUDE_SOURCES = {"ollamaspider"}


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
        "total_servers": tot_obs,
        "total_servers_clean": tot_obs_clean,
        "models": rows,
    }, separators=(",", ":")))

    print(f"  pulls.json     {len(rows)} models  {tot_pulls/1e9:.2f}B pulls vs "
          f"{tot_obs:,} installs ({tot_obs_clean:,} excluding questionable)")
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
