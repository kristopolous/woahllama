#!/usr/bin/env python3
"""Scrape ollama.com/library for each official model's advertised pull count.

The library index lists every official model with a cumulative pull count, a tag
count and a last-updated date. That pull count is the only public number for how
often a model is *downloaded*, which is a different act from what this survey
measures - what is *left running on an exposed server*. Holding the two side by
side is the point; see build_pulls.py for the comparison and its caveats.

Cached to library_pulls.json with the fetch date, so the series can be re-run
later and the counts diffed over time. Re-running overwrites today's entry and
keeps earlier ones."""
import json, pathlib, re, sys, datetime, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "pipeline" / "library_pulls.json"
URL = "https://ollama.com/library?sort=popular"
UA = "woah-llama-survey/1.0 (one-off research scrape of public model metadata)"

_SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9}
# one <li> per model: the /library/<name> anchor, then the pull count and tag
# count as bare <span>s next to their "Pulls" / "Tags" labels.
_CARD = re.compile(
    r'href="/library/(?P<name>[^"?/]+)"'
    r'(?P<rest>.*?)(?=href="/library/|\Z)', re.S)
_PULLS = re.compile(r'<span\s*>\s*([\d.]+)([KMB]?)\s*</span>\s*'
                    r'<span class="hidden sm:flex">\s*(?:&nbsp;)?\s*Pulls', re.S)
_TAGS = re.compile(r'<span\s*>\s*([\d,]+)\s*</span>\s*'
                   r'<span class="hidden sm:flex">\s*(?:&nbsp;)?\s*Tags', re.S)
_UPDATED = re.compile(r'title="([A-Z][a-z]{2} \d{1,2}, \d{4}[^"]*)"')


def parse(html):
    out = {}
    for m in _CARD.finditer(html):
        name, rest = m.group("name"), m.group("rest")
        p = _PULLS.search(rest)
        if not p:
            continue
        pulls = int(float(p.group(1)) * _SUFFIX.get(p.group(2), 1))
        t = _TAGS.search(rest)
        u = _UPDATED.search(rest)
        out[name] = {"pulls": pulls,
                     "tags": int(t.group(1).replace(",", "")) if t else None,
                     "updated": u.group(1) if u else None}
    return out


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    models = parse(html)
    if len(models) < 100:
        # the page is server-rendered HTML with no API behind it, so a layout
        # change shows up as a near-empty parse. Fail loudly rather than
        # silently shipping a chart built on ten models.
        print(f"! parsed only {len(models)} models - ollama.com layout probably "
              f"changed; keeping previous snapshot", file=sys.stderr)
        return 1
    hist = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    day = datetime.date.today().isoformat()
    hist[day] = models
    CACHE.write_text(json.dumps(hist, indent=0, sort_keys=True))
    total = sum(m["pulls"] for m in models.values())
    print(f"library_pulls: {len(models)} models, {total/1e9:.2f}B pulls total "
          f"({len(hist)} snapshot day(s) cached)")
    for n, m in sorted(models.items(), key=lambda kv: -kv[1]["pulls"])[:8]:
        print(f"   {n:24} {m['pulls']/1e6:8.1f}M")
    return 0


if __name__ == "__main__":
    sys.exit(main())
