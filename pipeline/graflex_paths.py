"""Where the graflex captures live, and which runs are safe to read.

The drop has been reorganised more than once. Two layouts are in the wild:

    tmp/graflex/graflex/<rundate>/...   the older nesting
    tmp/graflex/<rundate>/...           the current one, tmp itself being the
                                        symlink into the graflex drop

Rather than hard-coding either, find the directory that actually contains
<rundate> directories and work from there. Callers that only want flat files
(the original drop) still get the root.

A run that is still being written must not be ingested: a half-finished sweep
looks exactly like a real drop in host counts, and it would silently pull every
chart down. Runs named in `tmp/.ingest-skip` (one run id per line, `#` comments)
are excluded. Delete the line when the sweep finishes.
"""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNDATE = re.compile(r'^\d{14}$')


def root():
    """The directory holding the capture drop, or None if it is not mounted."""
    for cand in (os.path.join(ROOT, "tmp", "graflex"), os.path.join(ROOT, "tmp")):
        if os.path.isdir(cand):
            return cand
    return None


def skiplist():
    """Run ids the operator has marked as still in progress."""
    out = set()
    g = root()
    if not g:
        return out
    for p in (os.path.join(g, ".ingest-skip"),
              os.path.join(ROOT, "tmp", ".ingest-skip")):
        if os.path.isfile(p):
            for line in open(p):
                line = line.split("#")[0].strip()
                if line:
                    out.add(line)
    return out


def run_dirs():
    """Every complete run directory, as (run_id, path), oldest first.

    run_id is the eight-digit date, which is what the databases key on; the
    directory name carries a time as well, so two sweeps on one day merge.
    """
    g = root()
    if not g:
        return []
    bases = [g] + ([os.path.join(g, "graflex")]
                   if os.path.isdir(os.path.join(g, "graflex")) else [])
    skip, out = skiplist(), []
    for base in bases:
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if not RUNDATE.match(name) or not os.path.isdir(d) or name in skip:
                continue
            out.append((name[:8], d))
    return sorted(out)
