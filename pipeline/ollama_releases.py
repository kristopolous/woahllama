#!/usr/bin/env python3
"""Map an Ollama version string to the date that version was released.

The `ollama/` clone's tag history is the authority: every release is tagged
`vX.Y.Z` and the tag's creation date is the release date. Release candidates and
CI tags (`-rc0`, `-citest0`) are dropped - no deployed server reports one, and
they would put a version's date days before the release people actually got.

Written to ollama_releases.json so the rest of the pipeline does not need the
clone present. Re-run after pulling `ollama/` to pick up new releases."""
import json, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLONE = ROOT / "ollama"
OUT = ROOT / "pipeline" / "ollama_releases.json"

# vMAJOR.MINOR.PATCH and nothing else: anything with a suffix is a pre-release
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def main():
    if not (CLONE / ".git").exists():
        print(f"  {CLONE} is not a git clone; skipping", file=sys.stderr)
        return 1
    out = subprocess.run(
        ["git", "-C", str(CLONE), "for-each-ref",
         "--format=%(refname:short)\t%(creatordate:short)", "refs/tags"],
        capture_output=True, text=True, check=True).stdout

    rel = {}
    for line in out.splitlines():
        tag, _, date = line.partition("\t")
        m = TAG.match(tag.strip())
        if not m or not date.strip():
            continue
        ver = ".".join(m.groups())
        # a tag can be moved or re-cut; the earliest date is when it shipped
        if ver not in rel or date < rel[ver]:
            rel[ver] = date.strip()

    if len(rel) < 50:
        print(f"! only {len(rel)} release tags found - is the clone shallow?",
              file=sys.stderr)
        return 1

    key = lambda v: tuple(int(x) for x in v.split("."))
    ordered = sorted(rel, key=key)
    OUT.write_text(json.dumps(
        {"releases": {v: rel[v] for v in ordered},
         "first": rel[ordered[0]], "last": rel[ordered[-1]]},
        indent=0, sort_keys=False))
    print(f"  ollama_releases: {len(rel)} releases, "
          f"{ordered[0]} ({rel[ordered[0]]}) .. {ordered[-1]} ({rel[ordered[-1]]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
