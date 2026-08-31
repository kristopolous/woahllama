"""Aggregate the private wider survey into per-model 'hoarding' stats.

For each model, how large is the library of a typical host that runs it?  This
separates the defaults that sit on minimal single-purpose boxes from the
specialised and cloud-proxied models that ride on big multi-model rigs.

Input is the private host-level survey (never published).  Output is aggregate
only: one row per model with its host count, mean library size, and vendor.
"""
import collections, json, pathlib, re, statistics, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "full-survey-private.json"
SERVICES = {"ollama", "vllm", "llama.cpp", "lmstudio", "sglang"}
MIN_HOSTS = 12

sys.path.insert(0, str(ROOT / "pipeline"))
from vendors import vendor as vendor_of


def main():
    if not SRC.exists():
        print("  wider survey absent (private); keeping existing hoarding.json")
        return
    d = json.loads(SRC.read_text())
    hosts = [set(r.get("models") or []) for r in d
             if r.get("service") in SERVICES and r.get("models")]
    size = [len(h) for h in hosts]
    by = collections.defaultdict(list)
    for h in hosts:
        n = len(h)
        for m in h:
            by[m].append(n)

    models = []
    for name, sizes in by.items():
        if len(sizes) < MIN_HOSTS:
            continue
        base = name.split("/")[-1].split(":")[0]
        safe = re.sub(r'(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}', r'\1.\2.x.x', name)
        models.append([safe, len(sizes), round(statistics.mean(sizes), 1),
                       vendor_of(name)])
    models.sort(key=lambda r: -r[2])

    out = {
        "hosts": len(hosts),
        "overall_mean": round(statistics.mean(size), 1),
        "overall_median": statistics.median(size),
        "models": models,
    }
    (ROOT / "site" / "data" / "hoarding.json").write_text(
        json.dumps(out, separators=(",", ":")))
    print(f"  hoarding.json  {len(hosts)} hosts, {len(models)} models "
          f"(>= {MIN_HOSTS} hosts), mean library {out['overall_mean']}")


if __name__ == "__main__":
    main()
