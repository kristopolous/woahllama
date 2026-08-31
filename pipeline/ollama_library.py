"""Resolve Ollama library tags to parameter counts, quantisation and blob size.

Half the model names in the survey state their size in the tag (`gpt-oss:120b`,
`deepseek-r1:32b-qwen-distill-q8_0`).  The other half are `:latest`, which says
nothing on its own.  ollama.com/library/<model>/tags lists every tag with its
manifest digest, so `latest` can be resolved by finding another tag that shares
its digest - `llama3.2:latest` and `llama3.2:3b-instruct-q4_K_M` are the same
blob, and the second one names the size.

Results are cached to disk; re-running only fetches what is missing.
"""
import json, pathlib, re, sys, time, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "pipeline" / "library_cache.json"
UA = "woah-llama-survey/1.0 (one-off research scrape of public model metadata)"
DELAY = 0.7

# "a80c4f17acd5 • 2.0GB • 128K context window"
_ROW = re.compile(
    r'/library/(?P<model>[^:"]+):(?P<tag>[\w.\-]+)"'
    r'(?P<rest>.{0,1200}?)font-mono">\s*(?P<digest>[0-9a-f]{12})\s*</span>'
    r'\s*(?:&bull;|•)\s*(?P<size>[\d.]+)(?P<unit>[KMGT]B)',
    re.S)
_UNIT = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def parse(html, model):
    out = {}
    for m in _ROW.finditer(html):
        if m.group("model") != model:
            continue
        tag = m.group("tag")
        if tag in out:
            continue
        out[tag] = {"digest": m.group("digest"),
                    "bytes": int(float(m.group("size")) * _UNIT[m.group("unit")])}
    return out


def fetch(model):
    url = f"https://ollama.com/library/{model}/tags"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return parse(r.read().decode("utf-8", "replace"), model)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}           # not a library model (a local rename, a typo)
        raise


def main(names):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [n for n in names if n not in cache]
    print(f"{len(cache)} cached, fetching {len(todo)}", flush=True)
    for i, name in enumerate(todo, 1):
        try:
            cache[name] = fetch(name)
        except Exception as e:
            print(f"  ! {name}: {e}", file=sys.stderr)
            continue
        if i % 25 == 0 or i == len(todo):
            CACHE.write_text(json.dumps(cache))
            hit = sum(1 for v in cache.values() if v)
            print(f"  {i}/{len(todo)}  {name:28} {len(cache[name]):3} tags"
                  f"   ({hit} models resolved)", flush=True)
        time.sleep(DELAY)
    CACHE.write_text(json.dumps(cache))
    return cache


if __name__ == "__main__":
    import sqlite3
    con = sqlite3.connect(ROOT / "survey.db")
    rows = con.execute("""SELECT m.base, count(DISTINCT sm.server_id) n
        FROM model m JOIN server_model sm ON sm.model_id=m.id
        WHERE sm.source_id IN (1,2) GROUP BY m.base ORDER BY n DESC""").fetchall()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    names = [b for b, _ in rows if "/" not in b and not b.startswith("hf.co")][:limit]
    main(names)
