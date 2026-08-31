"""Derive parameter count and quantisation for every model name.

Three sources, in order of trust:

  1. the tag says so outright - `gpt-oss:120b`, `deepseek-r1:32b-qwen-distill-q8_0`
  2. the base name says so - `hf.co/OBLITERATUS/Qwen3.8-27B-OBLITERATED`
  3. the ollama.com library resolves it - `llama3.2:latest` shares a manifest
     digest with `llama3.2:3b-instruct-q4_K_M`, which names both

Ollama's own default for an unqualified tag is almost always a 4-bit K-quant,
but that is left to the digest lookup to establish rather than assumed here.
"""
import json, pathlib, re, sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "pipeline" / "library_cache.json"

# 120b / 1.5b / 135m / 8x7b (total) / 30b-a3b (total is the 30b)
_PLAIN = re.compile(r'(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*([bm])(?![a-z])', re.I)
_MIXTURE = re.compile(r'(?<![a-z0-9.])(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*b(?![a-z])', re.I)
# gemma3n's e4b / qwen3's a3b: only used when nothing plainer is present
_EFF = re.compile(r'(?<![a-z0-9.])[ae](\d+(?:\.\d+)?)\s*b(?![a-z])', re.I)

_QUANT = re.compile(
    r'(?<![a-z0-9])('
    r'iq\d(?:_[a-z0-9]+)*'          # iq3_XS
    r'|q\d(?:_[0-9]|_k(?:_[sml])?)?'  # q4_0, q4_K_M, q6_K, q8_0
    r'|fp?16|bf16|fp?32|f32'
    r'|int[48]'
    r')(?![a-z0-9])', re.I)

# a params figure this large is a byte count or a date, not a model
MAX_B = 2000


def params_b(*texts):
    """Billions of parameters, or None."""
    for t in texts:
        if not t:
            continue
        m = _MIXTURE.search(t)          # 8x7b -> 56B total
        if m:
            v = int(m.group(1)) * float(m.group(2))
            if v <= MAX_B:
                return v
        best = None
        for m in _PLAIN.finditer(t):
            v = float(m.group(1))
            if m.group(2).lower() == "m":
                v /= 1000.0
            elif v > MAX_B:
                continue
            best = v if best is None else max(best, v)
        if best is not None:
            return best
        m = _EFF.search(t)              # e4b / a3b when nothing else is given
        if m:
            v = float(m.group(1))
            if v <= MAX_B:
                return v
    return None


def quant(*texts):
    for t in texts:
        if not t:
            continue
        m = _QUANT.search(t)
        if m:
            q = m.group(1).lower().replace("fp", "f")
            return {"f16": "f16", "bf16": "bf16", "f32": "f32"}.get(q, q)
    return None


def quant_class(q):
    if not q:
        return None
    if q.startswith("iq"):
        return "q" + q[2]        # i-quants fold into their bit depth: they are a
                                 # different packing, not a different precision
    if q.startswith("q"):
        return "q" + q[1]
    if q in ("f16", "bf16"):
        return "16-bit"
    if q in ("f32", "int8", "int4"):
        return {"f32": "32-bit", "int8": "q8", "int4": "q4"}[q]
    return q


SIZE_BANDS = [(1.5, "under 1.5B"), (4, "1.5–4B"), (9, "4–9B"), (16, "9–16B"),
              (40, "16–40B"), (90, "40–90B"), (1e9, "90B+")]


def size_band(b):
    if b is None:
        return None
    for hi, label in SIZE_BANDS:
        if b < hi:
            return label
    return None


DDL = """
DROP TABLE IF EXISTS library_tag;
CREATE TABLE library_tag(model TEXT, tag TEXT, digest TEXT, bytes INT,
                         PRIMARY KEY(model, tag)) WITHOUT ROWID;
CREATE INDEX library_tag_digest ON library_tag(model, digest);

DROP TABLE IF EXISTS model_meta;
CREATE TABLE model_meta(
  model_id INTEGER PRIMARY KEY,
  params_b REAL, size_band TEXT,
  quant TEXT, quant_class TEXT,
  bytes INT,
  source TEXT,          -- tag | name | library
  is_cloud INT          -- a `-cloud` tag is proxied to Ollama's hosted service,
                        -- so the weights are not on the machine at all
);
CREATE INDEX model_meta_band ON model_meta(size_band);
CREATE INDEX model_meta_quant ON model_meta(quant_class);
"""


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    con.executescript(DDL)

    lib = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = [(m, t, v["digest"], v["bytes"])
            for m, tags in lib.items() for t, v in tags.items()]
    con.executemany("INSERT OR REPLACE INTO library_tag VALUES(?,?,?,?)", rows)
    print(f"library: {len(lib)} models queried, "
          f"{sum(1 for v in lib.values() if v)} with tags, {len(rows)} tag rows")

    # digest -> the most descriptive tag sharing it, per model
    by_digest = {}
    for model, tags in lib.items():
        for tag, v in tags.items():
            key = (model, v["digest"])
            cur = by_digest.get(key)
            # prefer the tag that actually states a size
            score = (params_b(tag) is not None, len(tag))
            if cur is None or score > cur[0]:
                by_digest[key] = (score, tag, v["bytes"])

    out = []
    for mid, name, base, tag in con.execute("SELECT id, name, base, tag FROM model"):
        p, q, src, nbytes = params_b(tag), quant(tag), "tag", None
        if p is None:
            p2 = params_b(base)
            if p2 is not None:
                p, src = p2, "name"
        if q is None:
            q = quant(base)
        if (p is None or q is None) and base in lib:
            entry = lib[base].get(tag or "latest")
            if entry:
                nbytes = entry["bytes"]
                best = by_digest.get((base, entry["digest"]))
                if best:
                    _, alias, _ = best
                    if p is None:
                        p2 = params_b(alias)
                        if p2 is not None:
                            p, src = p2, "library"
                    if q is None:
                        q2 = quant(alias)
                        if q2 is not None:
                            q, src = q2, "library" if src == "tag" else src
        cloud = 1 if re.search(r'(?:^|[-:])cloud$', tag or '') else 0
        out.append((mid, p, size_band(p), q, quant_class(q), nbytes,
                    src if p is not None else None, cloud))
    con.executemany("INSERT INTO model_meta VALUES(?,?,?,?,?,?,?,?)", out)
    con.commit()

    nc, = con.execute(
        "SELECT count(*) FROM model_meta WHERE is_cloud=1").fetchone()
    print(f"\ncloud-proxied tags: {nc} model names "
          "(excluded from size and quantisation stats - the weights are not local)")

    tot, = con.execute(
        "SELECT count(DISTINCT server_id) FROM server_model WHERE source_id IN (1,2)").fetchone()
    for label, col in (("parameter size", "size_band"), ("quantisation", "quant_class")):
        n, = con.execute(f"""SELECT count(DISTINCT sm.server_id) FROM server_model sm
            JOIN model_meta mm ON mm.model_id=sm.model_id
            WHERE sm.source_id IN (1,2) AND mm.{col} IS NOT NULL""").fetchone()
        print(f"\n{label}: resolved for {n:,} of {tot:,} servers")
        for v, c in con.execute(f"""SELECT mm.{col}, count(*) FROM server_model sm
            JOIN model_meta mm ON mm.model_id=sm.model_id
            WHERE sm.source_id IN (1,2) AND mm.{col} IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC"""):
            print(f"    {v:12} {c:8,} installs")
    con.close()


if __name__ == "__main__":
    main()
