"""Stream historical revisions of a file out of a git repo.

The repos here hold thousands of near-identical snapshots (9.7GB uncompressed
across the three), so revisions are pulled through a single `git cat-file --batch`
process rather than one `git show` per commit.
"""
import subprocess
from collections import namedtuple

Rev = namedtuple("Rev", "commit ts data")


def revisions(repo, path, reverse=True):
    """Yield Rev(commit, unix_ts, bytes) for every commit touching `path`.

    Chronological order by default, which is what the run-length encoder needs.
    """
    log = subprocess.run(
        ["git", "-C", repo, "log", "--format=%H %ct", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout.split("\n")

    revs = [ln.split() for ln in log if ln.strip()]
    if reverse:
        revs.reverse()
    if not revs:
        return

    proc = subprocess.Popen(
        ["git", "-C", repo, "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    try:
        for commit, ts in revs:
            proc.stdin.write(f"{commit}:{path}\n".encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode()
            if "missing" in header or "ambiguous" in header:
                continue
            size = int(header.split()[2])
            blob = proc.stdout.read(size)
            proc.stdout.read(1)  # trailing newline
            yield Rev(commit, int(ts), blob)
    finally:
        proc.stdin.close()
        proc.stdout.close()
        proc.wait()


def at_head(repo, path):
    """Read a single revision at HEAD."""
    return subprocess.run(
        ["git", "-C", repo, "show", f"HEAD:{path}"],
        capture_output=True, check=True,
    ).stdout
