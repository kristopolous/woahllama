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
    """One row per machine, not per listener.

    A row in the capture is a host:port. One machine answers on many ports and
    hands out a different token on each, so counting rows inflates the fleet
    several-fold. Collapse to the IP, keeping a live listener over a dead one.
    """
    f = RAW / f"{group}.jsonl"
    if not f.exists():
        return None
    rows = [json.loads(l) for l in f.open() if l.strip()]
    rows = list({r["url"]: r for r in rows}.values())   # probe appends on resume
    best = {}
    for r in rows:
        ip = r["url"].split("//")[1].rsplit(":", 1)[0]
        cur = best.get(ip)
        if cur is None or (st(r, "api_tags") == 200 and st(cur, "api_tags") != 200):
            best[ip] = r
    return list(best.values())


def st(row, name):
    return row["paths"].get(name, {}).get("status")


def summarise(group, rows):
    """Per-path 200 rates for one group.

    For the control the bars must describe genuine Ollama hosts, so machines
    that the test itself unmasks as the honeypot kit are pulled out and counted
    separately. Leaving them in draws a bar implying a real daemon sometimes
    serves /wp-login.php, which is the opposite of what was measured.
    """
    live = [r for r in rows if st(r, "api_tags") == 200]
    served = collections.Counter()
    for r in live:
        served[sum(st(r, b) == 200 for b in BAIT)] += 1
    honeypot = [r for r in live if all(st(r, b) == 200 for b in BAIT)]
    bars = [r for r in live if r not in honeypot] if group == "control" else live
    return {
        "group": group,
        "unit": "machines (distinct IPs); one machine answers on many ports",
        "sampled": len(rows),
        "live": len(live),                       # answered /api/tags with 200
        "honeypot": len(honeypot),
        # the control's bars exclude the unmasked kit; the fleet's do not
        "bar_base": len(bars),
        # how many of the four bait paths each live host served, 0..4
        "bait_served": [served.get(i, 0) for i in range(5)],
        "paths": [{"path": LABEL[p],
                   "n200": sum(st(r, p) == 200 for r in bars),
                   "live": len(bars)}
                  for p in ["api_tags"] + BAIT + ["nonsense"]],
        # a catch-all answers the random path too; a curated kit 404s it
        "catchall": sum(st(r, "nonsense") == 200 for r in honeypot),
        "akia": sum(r["paths"].get("env", {}).get("akia", 0) > 0 for r in honeypot),
    }


def kit(rows):
    """How many distinct bodies each bait path returns across the honeypots.

    A handful of bodies across the whole fleet means one kit copied around. A
    different body per machine on the two paths that carry credentials means a
    per-listener canary token.
    """
    live = [r for r in rows if st(r, "api_tags") == 200]
    hp = [r for r in live if all(st(r, b) == 200 for b in BAIT)]
    out = []
    for p in BAIT:
        served = [r for r in hp if st(r, p) == 200]
        bodies = collections.Counter((r["paths"][p]["sha1"], r["paths"][p]["len"])
                                     for r in served)
        (_, top_len), top_n = bodies.most_common(1)[0]
        out.append({"path": LABEL[p], "hosts": len(served),
                    "distinct": len(bodies),
                    # the most common body and how much of the fleet shares it:
                    # one file on nearly every machine is the kit's fingerprint
                    "top_share": round(100 * top_n / len(served), 1),
                    "top_bytes": top_len,
                    "per_host": len(bodies) >= 0.95 * len(served)})
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
        "population": "Sample of phantom-catalogue hosts seen in the last 14 days, "
                      "against a control drawn from the wider survey's working list. "
                      "Everything is counted in machines: the capture is per "
                      "host:port and one machine answers on many ports.",
        "control_note": "The working list only ever tested /api/tags, so it is not a "
                        "list of genuine inference hosts. The three control machines "
                        "that served the bait paths were then asked a trivia question: "
                        "one returned a canned stub with a hardcoded 2024 timestamp, "
                        "one returned the phrase-bank filler, one returned the literal "
                        "string 'ok'. None is a real Ollama host. No genuine Ollama "
                        "host in the control served any bait path.",
        "groups": [summarise("phantom", phantom)] +
                  ([summarise("control", control)] if control else []),
        # every machine anywhere in the sweep that the test unmasked
        "confirmed_total": (summarise("phantom", phantom)["honeypot"]
                            + (summarise("control", control)["honeypot"] if control else 0)),
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
