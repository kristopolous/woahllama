#!/usr/bin/env python3
"""Resolve a model name to the date that model was actually released.

The date ollama.com/library shows is a *last updated* stamp - when the blob was
most recently re-pushed - and it is not a release date in any useful sense. It is
wrong by months, and it collapses separate releases onto one day: it dates both
qwen3.5 and qwen3.6 to 2026-09-01 when they are six weeks apart. Measured against
this survey's own evidence, 42 of 179 models had already been pulled onto an
observed host before the date ollama.com gives for them, which is impossible.

`model-list.json` is Artificial Analysis' leaderboard data
(https://artificialanalysis.ai/leaderboards/models). It carries a real
`releaseDate` for 644 models and is the authority here. Refresh it with:

    curl 'https://artificialanalysis.ai/leaderboards/models?is_open_weights=open_source&size_class=all' \\
      | perl -pe 's/<script>/\\n/g' /dev/stdin | grep totalPa \\
      | sed -E 's/^...................{8}/"/g' | sed 's^....)</script>^"^g' \\
      | jq -r 'fromjson' > model-list.json

That is positional parsing of someone else's markup and will break; this module
checks the record count and refuses to emit a near-empty map rather than quietly
dating everything wrong.

It is a benchmark leaderboard, so it only covers models notable enough to be
evaluated - no embedding models, no tinyllama, no community re-uploads. For those
a low percentile of the `modified_at` values observed across probed hosts is used
instead. That is roughly when the model started appearing, not a release date,
and everything downstream is told which of the two it got.

Matching runs most-precise-first. An Ollama name carries its size in the tag and
the catalogue carries it in the slug, so `qwen3.6:27b` flattens to `qwen3627b`
and hits `qwen3-6-27b` exactly - which dates that host to the 27B release on
2026-04-22 rather than to whichever qwen3.6 variant shipped first, six weeks
after 3.5. Only when the tag says nothing useful (`:latest`) does it fall back to
the family's earliest release.

Writes pipeline/model_releases.json, with both a per-tag and a per-base map."""
import json, pathlib, re, sqlite3, sys, datetime, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "model-list.json"
FOFA = ROOT / "fofa" / "fofa.db"
OUT = ROOT / "pipeline" / "model_releases.json"

# Split a name into comparable tokens, breaking on punctuation and at a
# letter->digit boundary, so `gemma4` and the slug `gemma-4-12b` line up.
# Deliberately NOT at digit->letter: that would cut `8b` into `8`+`b` and let
# `qwen3.8` match the slug `qwen3-8b`, which is Qwen3 at 8B and a different
# model from Qwen3.8 by sixteen months.
_SPLIT = re.compile(r"[^a-z0-9]+")
_LETNUM = re.compile(r"(?<=[a-z])(?=\d)")


def stub(name):
    """Flatten to bare alphanumerics. Exact matching on this is safe where
    prefix matching is not: `qwen3.8` and `qwen3-8b` flatten to `qwen38` and
    `qwen38b`, which are simply different strings - the size suffix's `b` is
    what separates the model line from the parameter count."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def tokens(name):
    out = []
    for part in _SPLIT.split((name or "").lower()):
        if part:
            out.extend(t for t in _LETNUM.split(part) if t)
    return tuple(out)


def load_catalogue():
    if not SRC.exists():
        return {}
    recs = []

    def walk(o):
        if isinstance(o, dict):
            if "releaseDate" in o and "slug" in o:
                recs.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(SRC.read_text()))
    if len(recs) < 100:
        print(f"! model-list.json parsed to only {len(recs)} records - the scrape "
              f"recipe has probably broken; refusing to use it", file=sys.stderr)
        return {}
    cat, by_stub = {}, {}
    for r in recs:
        cat.setdefault(tokens(r["slug"]), []).append(r["releaseDate"])
        by_stub.setdefault(stub(r["slug"]), []).append(r["releaseDate"])
    return cat, by_stub


def resolver(cat, by_stub):
    """Resolve a model name to a release date, most precise match first.

    1. the whole name, tag included, flattened and matched exactly. This is the
       variant's own release date and is the one to want.
    2. the base alone, as a *token* prefix of a catalogue slug, taking the
       earliest matching variant - the date the line first shipped. Token
       equality rather than string prefix is what stops `qwen3.8` matching
       `qwen3-8b`, since ('qwen','3','8') is not a prefix of ('qwen','3','8b').
    """
    keys = list(cat)

    def prefix_hits(t):
        return [d for k in keys if k[:len(t)] == t for d in cat[k]]

    def resolve(name):
        whole = (name or "").replace(":", "-")
        if stub(whole) in by_stub:
            return min(by_stub[stub(whole)]), "catalogue-tag"
        # the tag may name a variant the slug spells out further:
        # `qwen3.6:35b` -> ('qwen','3','6','35b') is a prefix of the slug
        # `qwen3-6-35b-a3b`, which is the release that actually dates it
        tw = tokens(whole)
        if tw in cat:
            return min(cat[tw]), "catalogue-tag"
        hits = prefix_hits(tw) if tw else []
        if hits:
            return min(hits), "catalogue-tag"
        # Base name, meaning the tag said nothing about which variant (`:latest`,
        # or no tag at all). Here the answer wanted is when the *line* first
        # shipped, so take the minimum over every catalogue entry under it -
        # NOT the record that happens to share the bare name. A stub-exact hit
        # on `deepseek-r1` lands on the R1-0528 revision and dates the line to
        # May 2025, five months after R1 actually shipped, which then makes
        # hundreds of honest hosts look like they pulled it before it existed.
        base = (name or "").split(":")[0]
        t = tokens(base)
        if not t:
            return None, None
        hits = prefix_hits(t)
        if t in cat:
            hits = hits + cat[t]
        if stub(base) in by_stub:
            hits = hits + by_stub[stub(base)]
        return (min(hits), "catalogue-family") if hits else (None, None)
    return resolve


def observed_first_pull():
    """When each model first shows up as pulled onto a probed host.

    `modified_at` is reported by the host, so it is only as good as that host's
    clock, and a single machine with a wrong date would otherwise set the whole
    model's date. Take a low percentile of the observations rather than the
    minimum, so one bad clock cannot move it."""
    if not FOFA.exists():
        return {}
    con = sqlite3.connect(FOFA)
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                       " AND name='tags_model'").fetchone():
        return {}
    obs = collections.defaultdict(list)
    for name, ts in con.execute(
            "SELECT name, modified_ts FROM tags_model"
            " WHERE modified_ts IS NOT NULL AND modified_ts > 1600000000"):
        base = (name or "").split(":")[0]
        if base:
            obs[base].append(ts)
    con.close()
    first = {}
    for base, ts in obs.items():
        ts.sort()
        # 5th percentile, but the minimum when there are too few to spare
        t = ts[0] if len(ts) < 20 else ts[len(ts) // 20]
        first[base] = datetime.datetime.fromtimestamp(
            t, datetime.UTC).date().isoformat()
    return first


def main():
    cat, by_stub = load_catalogue()
    resolve = resolver(cat, by_stub)
    seen = observed_first_pull()

    names, bases = set(), set(seen)
    if FOFA.exists():
        con = sqlite3.connect(FOFA)
        if con.execute("SELECT name FROM sqlite_master WHERE type='table'"
                       " AND name='daily_probe'").fetchone():
            for (models,) in con.execute(
                    "SELECT models FROM daily_probe WHERE service='ollama'"):
                for n in json.loads(models or "[]"):
                    if n:
                        names.add(n)
                        bases.add(n.split(":")[0])
        con.close()

    def entry(name, base):
        d, src = resolve(name)
        if d:
            # The catalogue wins outright. An earlier "observed pull" is not
            # evidence against it: that timestamp comes from the host's own
            # clock, and a box with a wrong date is far more likely than a model
            # that shipped before it was announced.
            return {"date": d, "source": src}
        if base in seen:
            return {"date": seen[base], "source": "first-seen"}
        return None

    tags, out, src_count = {}, {}, collections.Counter()
    for n in sorted(names):
        e = entry(n, n.split(":")[0])
        if e:
            tags[n] = e
            src_count[e["source"]] += 1
    for b in sorted(bases):
        e = entry(b, b)
        if e:
            out[b] = e

    OUT.write_text(json.dumps({"models": out, "tags": tags,
                               "n_catalogue": len(cat)}, indent=0, sort_keys=True))
    print(f"  model_releases: {len(tags)} tagged names and {len(out)} bases dated "
          f"from {len(cat)} catalogue entries")
    for k, v in src_count.most_common():
        print(f"    {k:20} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
