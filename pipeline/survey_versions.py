"""Aggregate a directory of `ollama version` probe responses into survey.json.

This is the project owner's own current-snapshot survey (~4.4k hosts), separate
from the git feeds.  It is the cleanest single discriminator in the project: a
real host reports one of many real versions in a natural long-tail, while the
templated responders rotate four fixed strings in a tight near-equal band, and
the two populations also split cleanly by port.
"""
import collections, glob, json, os, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "version"
PHANTOM = {"0.6.3", "0.1.34", "0.1.0", "0.1.20"}
_VER = re.compile(r'ollama version is ([0-9][0-9.]*)', re.I)
_PORT = re.compile(r':(\d+)$')


def main():
    if not SRC.exists():
        print("  version/ survey absent (private); keeping existing survey.json")
        return
    ver_of = {}
    silent = 0
    for f in glob.glob(str(SRC / "*")):
        host = os.path.basename(f)
        t = pathlib.Path(f).read_text(encoding="utf-8", errors="replace")
        m = _VER.search(t)
        if m:
            ver_of[host] = m.group(1)
        elif not t.strip():
            silent += 1
    total = silent + len(ver_of) + sum(  # anything neither parsed nor empty
        1 for f in glob.glob(str(SRC / "*"))
        if os.path.basename(f) not in ver_of
        and pathlib.Path(f).read_text(errors="replace").strip())
    n = len(glob.glob(str(SRC / "*")))

    hist = collections.Counter(ver_of.values())
    port = lambda h: (int(_PORT.search(h).group(1)) if _PORT.search(h) else None)
    def split_ports(hosts):
        c = collections.Counter(port(h) for h in hosts if port(h))
        return {"on_11434": c.get(11434, 0), "top": c.most_common(6)}

    phantom_hosts = [h for h, v in ver_of.items() if v in PHANTOM]
    real_hosts = [h for h, v in ver_of.items() if v not in PHANTOM]

    out = {
        "total": n,
        "responded": len(ver_of),
        "silent": n - len(ver_of),
        "templated": len(phantom_hosts),
        "real": len(real_hosts),
        "real_distinct_versions": len({ver_of[h] for h in real_hosts}),
        "phantom_versions": sorted(PHANTOM),
        # histogram, most common first, flagged; capped for payload
        "hist": [[v, c, v in PHANTOM] for v, c in hist.most_common(60)],
        "ports_templated": split_ports(phantom_hosts),
        "ports_real": split_ports(real_hosts),
    }
    (ROOT / "site" / "data" / "survey.json").write_text(
        json.dumps(out, separators=(",", ":")))
    r = out
    print(f"  survey.json  {n} hosts: {r['templated']} templated "
          f"({100*r['templated']/r['responded']:.0f}% of responders), "
          f"{r['real']} real across {r['real_distinct_versions']} versions")
    print(f"    templated on 11434: {r['ports_templated']['on_11434']}/{r['templated']}; "
          f"real on 11434: {r['ports_real']['on_11434']}/{r['real']}")


if __name__ == "__main__":
    main()
