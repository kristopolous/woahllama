#!/usr/bin/env python3
"""Where the responder fleet is hosted, and the checks that came back empty.

The positive result is narrow and solid: every phantom-catalogue host that FOFA
also saw is on AWS, and none of the ten thousand non-AWS hosts in the same
capture is one. The counts are aggregate only - no addresses leave here.

The negative results matter as much, because the obvious explanation for the
fake premium model names is that people follow Ollama's own documented advice
to `ollama cp` a local model to an OpenAI name. That is a real, documented
technique, and this file records where the evidence for it should have been and
was not. Those figures come from the Ollama repository's own git history, which
is also the source for docs.ollama.com, so it is the full record rather than a
sample.

Writes site/data/hosting.json."""
import collections, json, pathlib, sqlite3, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
FOFA = ROOT / "fofa" / "fofa.db"
CLONE = ROOT / "ollama"

# names the fleet actually advertises, against the names the documentation uses
DOC_EXAMPLES = ("gpt-3.5-turbo", "claude-3-5-sonnet")
OBSERVED = ("claude-3-opus", "gpt-4", "gpt-4o")


def is_aws(org, cloud):
    return (cloud or "").lower().startswith("aws") or "amazon" in (org or "").lower()


def doc_history():
    """Every `ollama cp` example that ever shipped in the compatibility docs."""
    if not (CLONE / ".git").exists():
        return None
    out = {"examples": collections.Counter(), "anthropic_first": None}
    for path in ("docs/openai.md", "docs/api/openai-compatibility.mdx",
                 "docs/api/anthropic-compatibility.mdx"):
        try:
            commits = subprocess.run(
                ["git", "-C", str(CLONE), "log", "--all", "--format=%H", "--", path],
                capture_output=True, text=True, check=True).stdout.split()
        except subprocess.CalledProcessError:
            continue
        for c in commits:
            body = subprocess.run(["git", "-C", str(CLONE), "show", f"{c}:{path}"],
                                  capture_output=True, text=True).stdout
            for line in body.splitlines():
                line = line.strip()
                if line.startswith("ollama cp "):
                    out["examples"][line] += 1
        if path.endswith("anthropic-compatibility.mdx") and commits:
            d = subprocess.run(
                ["git", "-C", str(CLONE), "log", "-1", "--format=%ad", "--date=short",
                 commits[-1]], capture_output=True, text=True).stdout.strip()
            out["anthropic_first"] = d or None
    out["examples"] = dict(out["examples"])
    return out


def main():
    if not FOFA.exists():
        print("  hosting: fofa.db absent; skipping", file=sys.stderr)
        return 0
    con = sqlite3.connect(ROOT / "survey.db")
    fc = sqlite3.connect(FOFA)
    phantom = {r[0] for r in con.execute(
        "SELECT server_id FROM questionable_server WHERE phantom=1")}
    u2i = {u: i for i, u in con.execute("SELECT id,url FROM server")}

    tab = collections.Counter()
    for ip, port, org, cloud in fc.execute(
            "SELECT ip,port,asn_org,cloud FROM fofa_host"):
        i = u2i.get(f"http://{ip}:{port}")
        if i is None:
            continue
        tab[(is_aws(org, cloud), i in phantom)] += 1
    aws_p, aws_n = tab[(True, True)], tab[(True, False)]
    oth_p, oth_n = tab[(False, True)], tab[(False, False)]
    total = aws_p + aws_n + oth_p + oth_n
    rate = (aws_p + oth_p) / total if total else 0

    # names, as reported by hosts, from the probe captures
    names = collections.Counter()
    for (n,) in fc.execute("SELECT name FROM tags_model"):
        b = (n or "").split(":")[0].lower()
        if b:
            names[b] += 1

    # the blob every premium alias resolves to
    blob = fc.execute(
        "SELECT param_size, quant, family, COUNT(*) FROM tags_model"
        " WHERE lower(name) LIKE 'gpt-4%' OR lower(name) LIKE 'claude-3%'"
        " GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 1").fetchone()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hosting.json").write_text(json.dumps({
        "aws": {"phantom": aws_p, "other": aws_n},
        "not_aws": {"phantom": oth_p, "other": oth_n},
        "overall_rate": round(100 * rate, 1),
        "expected_if_even": round((oth_p + oth_n) * rate),
        "doc_examples": doc_history(),
        "name_counts": {n: names.get(n, 0) for n in DOC_EXAMPLES + OBSERVED},
        "alias_blob": ({"params": blob[0], "quant": blob[1], "family": blob[2],
                        "rows": blob[3]} if blob else None),
    }, separators=(",", ":")))

    print(f"  hosting.json   AWS {aws_p:,} phantom / {aws_p+aws_n:,} hosts; "
          f"elsewhere {oth_p:,} / {oth_p+oth_n:,}")
    print(f"    even spread would put ~{round((oth_p+oth_n)*rate):,} off AWS")
    for n in DOC_EXAMPLES + OBSERVED:
        print(f"    {n:20} {names.get(n,0):6} rows")
    con.close(); fc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
