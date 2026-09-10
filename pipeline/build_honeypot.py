"""Turn the attack-path probe in probe/honeypot_probe/ into site/data/honeypot.json.

The probe (honeypot_probe.py) asks each host for /api/tags and for four things a
scanner would ask for. A real Ollama daemon serves the first and 404s the rest.
A multi-protocol honeypot serves all of them.

Two groups: a 10% sample of the phantom-catalogue fleet, and a control drawn from
the wider survey's verified-working Ollama hosts. Only aggregates are emitted;
the raw capture holds live host addresses and stays private.
"""
import collections, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW  = ROOT / "probe" / "honeypot_probe"
BAIT = ["git", "env", "wp", "mysql"]
LABEL = {"api_tags": "/api/tags", "git": "/.git/config", "env": "/.env",
         "wp": "/wp-login.php", "mysql": "/wp-content/mysql.sql",
         "nonsense": "random path"}


def load(group):
    f = RAW / f"{group}.jsonl"
    if not f.exists():
        return None
    rows = [json.loads(l) for l in f.open() if l.strip()]
    # dedupe on url, last write wins (the probe appends on --resume)
    return list({r["url"]: r for r in rows}.values())


def st(row, name):
    return row["paths"].get(name, {}).get("status")


def summarise(group, rows):
    live = [r for r in rows if st(r, "api_tags") == 200]
    served = collections.Counter()
    for r in live:
        served[sum(st(r, b) == 200 for b in BAIT)] += 1
    honeypot = [r for r in live if all(st(r, b) == 200 for b in BAIT)]
    return {
        "group": group,
        "sampled": len(rows),
        "live": len(live),                       # answered /api/tags with 200
        "honeypot": len(honeypot),
        # how many of the four bait paths each live host served, 0..4
        "bait_served": [served.get(i, 0) for i in range(5)],
        # per-path 200 rate among live hosts, for the path table
        "paths": [{"path": LABEL[p],
                   "n200": sum(st(r, p) == 200 for r in live),
                   "live": len(live)}
                  for p in ["api_tags"] + BAIT + ["nonsense"]],
        # a catch-all answers the random path too; a curated kit 404s it
        "catchall": sum(st(r, "nonsense") == 200 for r in honeypot),
        "akia": sum(r["paths"].get("env", {}).get("akia", 0) > 0 for r in honeypot),
    }


def kit(rows):
    """How many distinct bodies each bait path returns across the honeypots.

    One body everywhere means one kit copied around. A different body per host
    on the two paths that carry credentials means a per-host canary token.
    """
    live = [r for r in rows if st(r, "api_tags") == 200]
    hp = [r for r in live if all(st(r, b) == 200 for b in BAIT)]
    out = []
    for p in BAIT:
        bodies = {r["paths"][p]["sha1"] for r in hp}
        sizes = {r["paths"][p]["len"] for r in hp}
        out.append({"path": LABEL[p], "hosts": len(hp), "distinct": len(bodies),
                    "bytes": sorted(sizes)[0] if len(sizes) == 1 else None})
    return out


def catalogue(rows):
    """What the honeypots advertise now, split by naming style.

    Half the live fleet still serves the frozen 2024 pool the chapter describes.
    The other half serves a single current-flagship name in Hugging Face form,
    so the bait catalogue has been restocked without the kit changing.
    """
    live = [r for r in rows if st(r, "api_tags") == 200 and r.get("models")]
    hp = [r for r in live if all(st(r, b) == 200 for b in BAIT)]
    hf = [r for r in hp if all("/" in m for m in r["models"])]
    old = [r for r in hp if r not in hf]
    top = lambda g, k: collections.Counter(
        m for r in g for m in r["models"]).most_common(k)
    return {"hf_hosts": len(hf), "old_hosts": len(old),
            "hf_single_model": sum(len(r["models"]) == 1 for r in hf),
            "hf_top": top(hf, 8), "old_top": top(old, 8)}


def main():
    phantom, control = load("phantom"), load("control")
    if not phantom:
        print("  attack-path capture absent (private); keeping existing honeypot.json")
        return
    out = {
        "note": "Each host was asked for /api/tags and for four paths a scanner "
                "would try. A real Ollama daemon serves the first and 404s the "
                "rest; a multi-protocol honeypot serves all of them.",
        "population": "10% sample of phantom-catalogue hosts seen in the last 14 "
                      "days, against a control of verified-working Ollama hosts.",
        "groups": [summarise("phantom", phantom)] +
                  ([summarise("control", control)] if control else []),
        "kit": kit(phantom),
        "catalogue": catalogue(phantom),
    }
    (ROOT / "site" / "data" / "honeypot.json").write_text(
        json.dumps(out, separators=(",", ":")))
    for g in out["groups"]:
        pc = 100 * g["honeypot"] / g["live"] if g["live"] else 0
        print(f"  {g['group']:8} {g['live']:4} live of {g['sampled']:4} sampled, "
              f"{g['honeypot']} honeypot ({pc:.1f}%)")


if __name__ == "__main__":
    main()
