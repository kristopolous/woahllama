"""Flag server-days that belong to an identical-catalogue cluster.

In April 2025 3,318 of 7,270 servers seen by OllamaSpider (46%) advertised the
same byte-identical 7-model catalogue for four days, then vanished together.
Whether that is a honeypot farm, one operator cloning an image, or a scanner
artifact, it is not 3,318 independent operators, and left alone it dominates
the model-popularity chart.

A server-day is flagged when its catalogue is shared exactly by at least
MIN_CLUSTER other servers on the same day AND holds at least MIN_MODELS models.
The model-count floor matters: ~127 servers legitimately run nothing but
`deepseek-r1:1.5b`, and that is a real fact about the population, not a cluster.

Intervals are walked with a sliding active-set so the cost is O(intervals)
rather than O(intervals x days).
"""
import collections, pathlib, sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAY = 86400
MIN_CLUSTER = 50
MIN_MODELS = 3

DDL = """
DROP TABLE IF EXISTS sybil_day;
CREATE TABLE sybil_day(
  source_id INT, server_id INT, day INT, cluster_size INT, n_models INT
);
CREATE INDEX sybil_day_sd ON sybil_day(server_id, day);
CREATE INDEX sybil_day_day ON sybil_day(day);
"""


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    con.executescript(DDL)
    d0 = con.execute("SELECT min(start_ts) FROM presence").fetchone()[0]
    d0 -= d0 % DAY
    ndays = (con.execute("SELECT max(end_ts) FROM presence").fetchone()[0] - d0)//DAY + 1

    out = []
    for sid, name in con.execute("SELECT id,name FROM source"):
        starts = collections.defaultdict(list)   # day -> [(server, model)]
        ends = collections.defaultdict(list)
        for sv, m, a, b in con.execute(
                "SELECT server_id,model_id,(start_ts-?)/?,(end_ts-?)/? "
                "FROM server_model WHERE source_id=?", (d0, DAY, d0, DAY, sid)):
            starts[max(a, 0)].append((sv, m))
            ends[min(b, ndays-1)].append((sv, m))

        active = collections.defaultdict(set)
        flagged = 0
        for day in range(ndays):
            for sv, m in starts.get(day, ()):
                active[sv].add(m)
            if active:
                sig = collections.defaultdict(list)
                for sv, ms in active.items():
                    if len(ms) >= MIN_MODELS:
                        sig[frozenset(ms)].append(sv)
                for cat, svs in sig.items():
                    if len(svs) >= MIN_CLUSTER:
                        flagged += len(svs)
                        out.extend((sid, sv, day, len(svs), len(cat)) for sv in svs)
            for sv, m in ends.get(day, ()):
                s = active.get(sv)
                if s is not None:
                    s.discard(m)
                    if not s:
                        del active[sv]
        print(f"  {name:24} {flagged:8} flagged server-days")

    con.executemany("INSERT INTO sybil_day VALUES(?,?,?,?,?)", out)
    con.commit()
    print(f"\ntotal {len(out):,} flagged server-days, "
          f"{con.execute('SELECT count(DISTINCT server_id) FROM sybil_day').fetchone()[0]:,} distinct servers")
    print("\nlargest clusters:")
    import datetime
    for day, cs, nm, n in con.execute(
            "SELECT day, max(cluster_size), max(n_models), count(*) FROM sybil_day"
            " GROUP BY day ORDER BY 2 DESC LIMIT 8"):
        d = datetime.datetime.fromtimestamp(d0+day*DAY, datetime.UTC).date()
        print(f"  {d}  biggest cluster {cs:5} servers x {nm} models")
    con.close()


if __name__ == "__main__":
    main()
