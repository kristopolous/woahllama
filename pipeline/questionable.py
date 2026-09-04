#!/usr/bin/env python3
"""Flag the servers Chapter 2 documents as probably not what they claim to be.

`clusters.py` already flags identical-catalogue *server-days*, which is a claim
about a day's snapshot. This is the other half: a claim about the machine. Four
tests, all decidable from the committed data without touching any of these hosts,
each one already described on the page:

  phantom      the catalogue is the dominant fixed model list, or that list with
               up to two entries missing (the same rule strange.py reports)
  impossible   it advertises a closed-weights commercial model that cannot exist
               as Ollama weights (gpt-4, claude-3-opus, gemini, ...)
  placeholder  it advertises a scratch or probe name (`test`, `demo`, `mario`)
  invented     a reported blob size disagrees with the real size of the tag it
               names, per ollama.com, by more than 2.5x either way

A server trips the flag if it ever failed any of them. The tests are deliberately
name-based and so are not perfect: a community re-upload that keeps a commercial
model's name in its own (`chatgpt-oss-...gguf`) trips `impossible` despite being
genuine open weights. That is a small share of the flagged set, and the flag is
offered as an optional exclusion on the page rather than applied by default.

Writes the `questionable_server` table. Must run after spider_sizes.py (needs
reported_size) and ollama_library.py (needs library_tag), and before build.py.
"""
import collections, pathlib, re, sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent

# closed-weights commercial names, shared with build_tags.py so the two agree
IMPOSSIBLE_RE = re.compile(
    r'^(gpt-?[345]|gpt-4o|o[134]\b|chatgpt|claude|gemini|grok|dall-?e)', re.I)
IMPOSSIBLE_NAMES = {"verif_sys"}
PLACEHOLDER = ("probe-nonexistent", "academic_research_probe", "world", "mario",
               "demo", "example", "test", "reflection", "costv1")
NEAR_MISSING = 2        # a subset of the phantom list missing this many entries
RATIO_HI, RATIO_LO = 2.5, 0.4
MIN_REAL_BYTES = 50_000_000     # below this it is an embedding or a cloud stub

DDL = """
DROP TABLE IF EXISTS questionable_server;
CREATE TABLE questionable_server(
  server_id INTEGER PRIMARY KEY,
  phantom INT, impossible INT, placeholder INT, invented INT
);
"""


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    con.executescript(DDL)
    names = dict(con.execute("SELECT id, name FROM model"))

    def is_placeholder(n):
        low = n.lower()
        return any(low == p or low.startswith(p) for p in PLACEHOLDER)

    imp_ids = {i for i, n in names.items()
               if IMPOSSIBLE_RE.match(n) or n.split(':')[0].lower() in IMPOSSIBLE_NAMES}
    plc_ids = {i for i, n in names.items() if is_placeholder(n)}

    cat = collections.defaultdict(set)
    for sv, m in con.execute("SELECT server_id, model_id FROM server_model"):
        cat[sv].add(m)
    top_sig = collections.Counter(
        frozenset(v) for v in cat.values()).most_common(1)[0][0]

    flags = collections.defaultdict(lambda: [0, 0, 0, 0])
    for sv, v in cat.items():
        if v == top_sig or (v < top_sig and len(v) >= len(top_sig) - NEAR_MISSING):
            flags[sv][0] = 1
        if v & imp_ids:
            flags[sv][1] = 1
        if v & plc_ids:
            flags[sv][2] = 1

    # ---- weights that do not match the tag they claim, as in strange.py ----
    lib = {(m, t): b for m, t, b in con.execute(
        "SELECT model, tag, bytes FROM library_tag")}
    base_tag = {i: (b, t) for i, b, t in con.execute("SELECT id, base, tag FROM model")}
    for sv, mid, hi in con.execute(
            "SELECT server_id, model_id, max_bytes FROM reported_size"):
        base, tag = base_tag[mid]
        real = lib.get((base, tag or "latest"))
        if not real or real < MIN_REAL_BYTES:
            continue
        if not (RATIO_LO <= hi / real <= RATIO_HI):
            flags[sv][3] = 1

    con.executemany("INSERT INTO questionable_server VALUES(?,?,?,?,?)",
                    ((sv, *f) for sv, f in flags.items()))
    con.commit()
    tot = len(cat)
    cols = ("phantom", "impossible", "placeholder", "invented")
    counts = [sum(f[i] for f in flags.values()) for i in range(4)]
    print(f"  questionable: {len(flags):,} of {tot:,} servers with a catalogue")
    for name, n in zip(cols, counts):
        print(f"    {name:12} {n:7,}")
    con.close()


if __name__ == "__main__":
    main()
