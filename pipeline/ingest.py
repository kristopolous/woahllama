"""Build survey.db from the three repos' git histories.

The three sources hold ~9.7GB of near-identical snapshots.  Exploding them into
one row per (snapshot, server, model) would be ~50M rows; instead presence is
run-length encoded, since only ~0.5% of servers change between consecutive
snapshots.  An interval means "present in every snapshot from start_seq to
end_seq inclusive", so a server that flaps produces several intervals and the
gaps are preserved rather than smoothed away.
"""
import sqlite3, sys, time, pathlib
from gitblobs import revisions
from parse import SOURCES, split_model

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "survey.db"


class Intern:
    """Assign stable integer ids, flushing new rows to the table as they appear."""

    def __init__(self, con, table, cols, key):
        self.con, self.table, self.cols, self.key = con, table, cols, key
        self.ids = {}
        for row in con.execute(f"SELECT id, {key} FROM {table}"):
            self.ids[row[1]] = row[0]
        self.pending = []

    def __call__(self, keyval, extra):
        i = self.ids.get(keyval)
        if i is None:
            i = self.ids[keyval] = len(self.ids) + 1
            self.pending.append((i, *extra))
        return i

    def flush(self):
        if self.pending:
            q = ",".join("?" * (len(self.cols) + 1))
            self.con.executemany(
                f"INSERT INTO {self.table}(id,{','.join(self.cols)}) VALUES({q})",
                self.pending)
            self.pending.clear()


class RunEncoder:
    """Collect contiguous runs keyed by an arbitrary hashable."""

    def __init__(self):
        self.open = {}      # key -> [start_seq, start_ts, last_seq, last_ts]
        self.closed = []

    def mark(self, key, seq, ts):
        r = self.open.get(key)
        if r is None or r[2] != seq - 1:
            if r is not None:
                self._close(key, r)
            self.open[key] = [seq, ts, seq, ts]
        else:
            r[2], r[3] = seq, ts

    def _close(self, key, r):
        self.closed.append((key, r[0], r[2], r[1], r[3], r[2] - r[0] + 1))

    def sweep(self, seq):
        """Close any run that did not appear in snapshot `seq`."""
        for key in [k for k, r in self.open.items() if r[2] < seq]:
            self._close(key, self.open.pop(key))

    def finish(self):
        for key, r in list(self.open.items()):
            self._close(key, r)
        self.open.clear()
        return self.closed


def ingest(con, src):
    sid = con.execute(
        "INSERT INTO source(name,repo,path,discovery) VALUES(?,?,?,?) RETURNING id",
        (src["name"], src["repo"], src["path"], src["discovery"])).fetchone()[0]

    servers = Intern(con, "server", ["url", "host", "port", "ip", "ip_int", "o1", "o2"], "url")
    models = Intern(con, "model", ["name", "base", "tag"], "name")
    pres, smod = RunEncoder(), RunEncoder()
    snaps = []
    t0 = time.time()

    for seq, rev in enumerate(revisions(ROOT / src["repo"], src["path"])):
        try:
            data = src["parse"](rev.data)
        except Exception as e:                      # a truncated mid-push commit
            print(f"  ! skipping {rev.commit[:8]}: {e}", file=sys.stderr)
            continue

        nmod = 0
        for (url, host, port, ip, ip_int), mods in data.items():
            o1 = o2 = None
            if ip:
                a, b = ip.split(".")[:2]
                o1, o2 = int(a), int(b)
            svid = servers(url, (url, host, port, ip, ip_int, o1, o2))
            pres.mark(svid, seq, rev.ts)
            for m in mods:
                base, tag = split_model(m)
                smod.mark((svid, models(m, (m, base, tag))), seq, rev.ts)
                nmod += 1

        pres.sweep(seq)
        smod.sweep(seq)
        snaps.append((sid, seq, rev.commit, rev.ts, len(data), nmod))

        if seq % 500 == 0:
            servers.flush(); models.flush()
            print(f"  {src['name']:22} snap {seq:5}  "
                  f"{len(data):5} servers  {time.time()-t0:5.0f}s", flush=True)

    servers.flush(); models.flush()
    con.executemany(
        "INSERT INTO snapshot(source_id,seq,commit_sha,ts,n_servers,n_model_rows)"
        " VALUES(?,?,?,?,?,?)", snaps)
    con.executemany(
        "INSERT INTO presence(source_id,server_id,start_seq,end_seq,start_ts,end_ts,n_snap)"
        f" VALUES({sid},?,?,?,?,?,?)", pres.finish())
    con.executemany(
        "INSERT INTO server_model(source_id,server_id,model_id,start_seq,end_seq,"
        f"start_ts,end_ts,n_snap) VALUES({sid},?,?,?,?,?,?,?)",
        ((k[0], k[1], *rest) for k, *rest in smod.finish()))
    con.commit()
    print(f"  {src['name']:22} done: {len(snaps)} snapshots, "
          f"{time.time()-t0:.0f}s", flush=True)


def main():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript((pathlib.Path(__file__).parent / "schema.sql").read_text())
    only = sys.argv[1:] 
    for src in SOURCES:
        if only and src["name"] not in only:
            continue
        ingest(con, src)
    con.close()


if __name__ == "__main__":
    main()
