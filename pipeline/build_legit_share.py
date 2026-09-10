"""Write site/data/legit_share.json: how much of the feed is still a real server.

Scope: OllamaSpider only, which is the feed the fake fleet lives in.

The hard part is separating the two populations *at the time they were seen*.
The catalogue test cannot do it, because a server running llama3 in early 2025
was running the most popular model of the moment, and the flag would call it
fake in hindsight. Reported size cannot do it either: the fleet's byte-exact
constant looks identical to a genuinely popular tag that everyone pulled from
the same re-push.

Port can. It is recorded on every observation in every snapshot, it is set by
whoever installed the thing rather than inferred by us, and nothing about a
model catalogue feeds into it. Ollama's default is 11434.

Counted in distinct IPs, which matters more here than anywhere else in the
survey. A single wildcard host that answers on every port it is asked about
lands in the feed once per port: 203.69.53.137 alone produced 3,315 "servers"
over nine days in April 2025, which is most of what used to look like the fake
fleet arriving that spring. It was one machine.

It is a proxy, not proof, so it is checked against the other evidence:
  * of spider hosts on 11434, 0.3% carry the phantom catalogue
  * of spider hosts on any other port, 66.2% do
  * of the honeypot listings confirmed by direct probe, 1 of 827 is on 11434
A real admin can of course move the port. At these ratios that is noise.
"""
import datetime, json, pathlib, sqlite3

ROOT   = pathlib.Path(__file__).resolve().parent.parent
OUT    = ROOT / "site" / "data" / "legit_share.json"
DAY    = 86400
SPIDER = "ollamaspider"
OLLAMA_PORT = 11434


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    sid = con.execute("SELECT id FROM source WHERE name=?", (SPIDER,)).fetchone()[0]
    d0, hi = con.execute(
        "SELECT min(start_ts), max(end_ts) FROM presence WHERE source_id=?",
        (sid,)).fetchone()
    d0 -= d0 % DAY
    n = (hi - d0) // DAY + 1
    rows = con.execute("""
        SELECT s.ip, s.host, s.port, p.start_ts, p.end_ts
          FROM presence p JOIN server s ON s.id = p.server_id
         WHERE p.source_id = ?""", (sid,)).fetchall()
    con.close()

    # distinct machines per day, not host:port rows
    std_d = [set() for _ in range(n)]
    oth_d = [set() for _ in range(n)]
    for ip, host, port, a, b in rows:
        who = ip or host
        if who is None:
            continue
        t = std_d if port == OLLAMA_PORT else oth_d
        for i in range(max((a - d0) // DAY, 0), min((b - d0) // DAY, n - 1) + 1):
            t[i].add(who)
    std   = [len(x) for x in std_d]
    other = [len(x) for x in oth_d]

    tot = [std[i] + other[i] for i in range(n)]
    share = [round(100 * std[i] / tot[i], 2) if tot[i] else None for i in range(n)]

    # quote the curve the chart draws, not single days
    def roll(v, w=15):
        out = []
        for i in range(n):
            win = [x for x in v[max(0, i - w // 2):i + w // 2 + 1] if x is not None]
            out.append(round(sum(win) / len(win), 2) if win else None)
        return out
    rs = roll(share)
    have = [i for i in range(n) if rs[i] is not None]
    first, last = have[0], have[-1]
    peak = max(have, key=lambda i: rs[i])
    # counts off the same 15-day mean the chart draws
    rstd, roth = roll(std), roll(other)
    std_peak = max(range(n), key=lambda i: rstd[i])

    other_share = [round(100 - share[i], 2) if share[i] is not None else None
                   for i in range(n)]
    # the month the fake side first overtakes Ollama's own port and stays ahead
    cross = None
    for i in range(n):
        if rstd[i] is not None and roth[i] > rstd[i] and all(
                roth[j] > rstd[j] for j in range(i, min(i + 30, n))):
            cross = i
            break
    out = {"day0": d0, "ndays": n, "std": std, "other": other, "cross_day": cross,
           "share": share, "other_share": other_share,
           "first_day": first, "first_share": rs[first],
           "peak_day": peak, "peak_share": rs[peak],
           "last_day": last, "last_share": rs[last],
           "std_peak_day": std_peak, "std_peak": round(rstd[std_peak]),
           "std_now": round(rstd[last]), "other_now": round(roth[last]),
           "source": SPIDER, "port": OLLAMA_PORT,
           "note": "Share of OllamaSpider's hosts answering on Ollama's own port, "
                   "per day. Port is recorded on every observation, so this splits "
                   "the feed at the time it was seen rather than in hindsight."}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    f = lambda i: datetime.datetime.fromtimestamp(d0 + i * DAY, datetime.UTC).strftime("%Y-%m-%d")
    print(f"  legit_share.json  {f(peak)} {rs[peak]}%  ->  {f(last)} {rs[last]}%")


if __name__ == "__main__":
    main()
