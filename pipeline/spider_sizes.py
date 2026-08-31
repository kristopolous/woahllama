"""Record the model byte sizes OllamaSpider reports, which the main ingest drops.

Size is the only field in any of the three feeds that can be checked against an
outside fact: ollama.com publishes the real blob size for every library tag, so
a server claiming `deepseek-r1:32b` at 78 GB is not serving the tag it names.
Stored per (server, model) as the range seen across all of history.
"""
import collections, json, pathlib, sqlite3
from gitblobs import revisions
from parse import canon_url

ROOT = pathlib.Path(__file__).resolve().parent.parent

DDL = """
DROP TABLE IF EXISTS reported_size;
CREATE TABLE reported_size(
  server_id INT, model_id INT,
  min_bytes INT, max_bytes INT, n_obs INT,
  PRIMARY KEY(server_id, model_id)
) WITHOUT ROWID;
"""


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    con.executescript(DDL)
    servers = dict(con.execute("SELECT url, id FROM server"))
    models = dict(con.execute("SELECT name, id FROM model"))

    acc = {}
    seen_rev = 0
    for rev in revisions(ROOT / "OllamaSpider", "url_models.json"):
        seen_rev += 1
        try:
            data = json.loads(rev.data)
        except Exception:
            continue
        for e in data:
            u = canon_url(e.get("url", ""))
            if not u:
                continue
            sid = servers.get(u[0])
            if sid is None:
                continue
            for m in e.get("models") or []:
                name, size = m.get("name"), m.get("size")
                if not name or size is None:
                    continue
                mid = models.get(name)
                if mid is None:
                    continue
                k = (sid, mid)
                cur = acc.get(k)
                if cur is None:
                    acc[k] = [size, size, 1]
                else:
                    cur[0] = min(cur[0], size)
                    cur[1] = max(cur[1], size)
                    cur[2] += 1
        if seen_rev % 500 == 0:
            print(f"  {seen_rev} revisions, {len(acc):,} (server,model) pairs", flush=True)

    con.executemany("INSERT INTO reported_size VALUES(?,?,?,?,?)",
                    ((s, m, v[0], v[1], v[2]) for (s, m), v in acc.items()))
    con.commit()
    print(f"{seen_rev} revisions -> {len(acc):,} size records")
    con.close()


if __name__ == "__main__":
    main()
