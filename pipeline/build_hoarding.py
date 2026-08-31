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
from vendors import vendor as vendor_of, is_uncensored

_IMAGE = re.compile(r'flux|stable-?diffusion|sdxl|sd3|dreamshaper|\.safetensors|\.ckpt|realvis|comfy', re.I)

# parameter count from a model name: 135m -> 0.135, 7b -> 7, 480b, 1t -> 1000
_SZ = re.compile(r'(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*([bmt])(?![a-z])', re.I)
_EFF = re.compile(r'(?<![a-z0-9.])[ae](\d+(?:\.\d+)?)\s*b(?![a-z])', re.I)  # e4b / a3b
def params_b(name):
    best = None
    for m in _SZ.finditer(name):
        v = float(m.group(1)); u = m.group(2).lower()
        v = v / 1000 if u == 'm' else v * 1000 if u == 't' else v
        if v <= 2000:
            best = v if best is None else max(best, v)
    if best is not None:
        return best
    m = _EFF.search(name)
    if m and float(m.group(1)) <= 2000:
        return float(m.group(1))
    return None


# resolve a base:latest (or any untagged size) to a parameter count via the
# ollama.com library cache: the tag's manifest digest matches a sized sibling tag.
_LIB = {}
_DIGEST_P = {}
def _load_lib():
    f = ROOT / "pipeline" / "library_cache.json"
    if not f.exists():
        return
    _LIB.update(json.loads(f.read_text()))
    for base, tags in _LIB.items():
        for tag, v in tags.items():
            pb = params_b(tag)
            if pb is not None:
                _DIGEST_P.setdefault((base, v["digest"]), pb)

def _from_library(base, tag):
    base = base.lower()          # library names are lowercase
    entry = _LIB.get(base, {}).get(tag or "latest") or _LIB.get(base, {}).get("latest")
    if not entry:
        return None
    # a sibling tag that names a size and shares this digest
    p = _DIGEST_P.get((base, entry["digest"]))
    if p is not None:
        return p
    # otherwise estimate from the download size (q4-ish ~0.6 GB per billion params)
    gb = entry["bytes"] / 1e9
    return round(gb / 0.6, 1) if gb else None

# community fine-tunes keep the base model's size (huihui_ai/<x>-abliterated is
# just an uncensored <x>), so strip the namespace and the fine-tune suffix.
_FORK = re.compile(r'[-_](abliterated|uncensored|heretic|lorablated|amoral|'
                   r'unfiltered|nsfw|unalign\w*|abliterate)\w*$', re.I)

def _candidate_bases(base):
    tail = base.rsplit("/", 1)[-1]
    cands = [base, tail]
    stripped = _FORK.sub("", tail)
    if stripped != tail:
        cands.append(stripped)
    if tail.startswith("text-embedding-"):
        cands.append(tail[len("text-embedding-"):])
    alias = re.sub(r'[-_](backup|copy|bak)\d*$', '', tail, flags=re.I)
    if alias != tail:
        cands.append(alias)
    # a trailing -v1.5 style version suffix the library base doesn't carry
    for c in list(cands):
        v = re.sub(r'-v\d+(?:\.\d+)*$', '', c, flags=re.I)
        if v != c and v not in cands:
            cands.append(v)
    return cands

def resolve_params(name):
    pb = params_b(name)
    if pb is not None:
        return pb
    base, _, tag = name.partition(":")
    for b in _candidate_bases(base):
        pb = params_b(b) or _from_library(b, tag)
        if pb is not None:
            return pb
    return None

def main():
    _load_lib()
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
        if len(sizes) < MIN_HOSTS or _IMAGE.search(name):
            continue
        base = name.split("/")[-1].split(":")[0]
        safe = re.sub(r'(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}', r'\1.\2.x.x', name)
        models.append([safe, len(sizes), round(statistics.mean(sizes), 1),
                       vendor_of(name), resolve_params(name),
                       1 if is_uncensored(name) else 0])
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
