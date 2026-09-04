#!/usr/bin/env python3
"""Additively merge the point-in-time FOFA and Shodan surveys and the daily
live-probe survey into survey.db as new sources, so build.py picks them up in
every chart. FOFA and Shodan hosts become a single-day presence at their scan
date (FOFA mtime / Shodan ts) - those are last-seen snapshots, not spans. The
live probe re-checks the same hosts on successive days, so it does give a span:
its presence runs from a host's first to its last online sighting. Idempotent:
prior rows for these sources are removed first. Does NOT touch the git-scanner
sources or the existing server_geo."""
import os, sqlite3, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse import split_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVEY = os.path.join(ROOT, "survey.db")
FOFA = os.path.join(ROOT, "fofa", "fofa.db")

def uts(s):
    if isinstance(s, int): return s
    try: return int(datetime.datetime.fromisoformat((s or '').replace('T',' ')[:19])
                    .replace(tzinfo=datetime.timezone.utc).timestamp())
    except: return None

def ip_fields(ip):
    try:
        a,b,c,d = (int(x) for x in ip.split('.'))
        return a, b, (a<<24)|(b<<16)|(c<<8)|d
    except: return None, None, None

def main():
    con = sqlite3.connect(SURVEY); c = con.cursor()
    fc = sqlite3.connect(FOFA); fq = fc.cursor()
    # ---- clean prior fofa/shodan sources (idempotent) ----
    old = [r[0] for r in c.execute("SELECT id FROM source WHERE discovery IN"
                                   " ('fofa-live','shodan-live','probe-live')")]
    for sid in old:
        for t in ("presence","server_model","snapshot"):
            c.execute(f"DELETE FROM {t} WHERE source_id=?", (sid,))
        c.execute("DELETE FROM source WHERE id=?", (sid,))
    # ---- server + model id maps ----
    surl = {u:i for i,u in c.execute("SELECT id,url FROM server")}
    next_sv = (max(surl.values())+1) if surl else 1
    mname = {n:i for i,n in c.execute("SELECT id,name FROM model")}
    next_m = (max(mname.values())+1) if mname else 1
    new_servers, new_models = [], []
    def server_id(ip, port):
        nonlocal next_sv
        url = f"http://{ip}:{port}"
        i = surl.get(url)
        if i is None:
            o1,o2,ipi = ip_fields(ip)
            i = surl[url] = next_sv; next_sv += 1
            # keep the invariant: ip is stored only when it parses to octets
            store_ip = ip if o1 is not None else None
            new_servers.append((i, url, ip, port, store_ip, ipi, o1, o2))
        return i
    def model_id(name):
        nonlocal next_m
        i = mname.get(name)
        if i is None:
            base, tag = split_model(name)
            i = mname[name] = next_m; next_m += 1
            new_models.append((i, name, base, tag))
        return i

    def add_source(name, repo, path, discovery, rows_iter, with_models):
        sid = c.execute("INSERT INTO source(name,repo,path,discovery) VALUES(?,?,?,?) RETURNING id",
                        (name, repo, path, discovery)).fetchone()[0]
        pres, smod, snaps = [], [], {}
        # rows are (host, port, first-seen, last-seen, n_sightings, models); the
        # point-in-time sources pass the same timestamp for both ends
        for host, port, ts0, ts1, nseen, models in rows_iter:
            a, b = uts(ts0), uts(ts1)
            if a is None or b is None or not port: continue
            ip = host.split(':')[0]
            svid = server_id(ip, port)
            pres.append((sid, svid, 0, 0, a, b, nseen))
            if with_models:
                # models is {name: (first_ts, last_ts, n_sightings)}
                for m, (ma, mb, mn) in models.items():
                    smod.append((sid, svid, model_id(m), 0, 0, ma, mb, mn))
        # one nominal snapshot row (build.py keys on ts, not seq)
        c.execute("INSERT INTO snapshot(source_id,seq,commit_sha,ts,n_servers,n_model_rows)"
                  " VALUES(?,?,?,?,?,?)", (sid, 0, discovery, 0, len(pres), len(smod)))
        c.executemany("INSERT INTO presence(source_id,server_id,start_seq,end_seq,start_ts,end_ts,n_snap)"
                      " VALUES(?,?,?,?,?,?,?)", pres)
        c.executemany("INSERT INTO server_model(source_id,server_id,model_id,start_seq,end_seq,"
                      "start_ts,end_ts,n_snap) VALUES(?,?,?,?,?,?,?,?)", smod)
        return sid, len(pres), len(smod)

    import json
    def fofa_rows():
        for ip, port, mt, models in fq.execute("SELECT ip,port,mtime,models FROM fofa_host WHERE mtime!=''"):
            t = uts(mt)
            yield (f"{ip}:{port}", port, mt, mt, 1,
                   {m[0]: (t, t, 1) for m in json.loads(models) if m and m[0]})
    def shodan_rows():
        for host, port, ts in fq.execute("SELECT ip,port,ts FROM shodan_host WHERE ts!=''"):
            yield f"{host}:{port}", port, ts, ts, 1, {}

    def probe_rows():
        """The daily live probe re-checks the same hosts, so collapse each host's
        dated sightings into a first-to-last span. Only the Ollama service: the
        other inference servers in the same capture are different software and
        do not belong in a survey of Ollama hosts."""
        if not fq.execute("SELECT name FROM sqlite_master WHERE type='table'"
                          " AND name='daily_probe'").fetchone():
            return
        span, mspan, ports = {}, {}, {}
        for host, port, ck, models in fq.execute(
                "SELECT host,port,checked,models FROM daily_probe WHERE service='ollama'"
                " ORDER BY checked"):
            t = uts(ck)
            if t is None: continue
            ports[host] = port
            a, b, n = span.get(host, (t, t, 0))
            span[host] = (min(a, t), max(b, t), n + 1)
            for m in json.loads(models or "[]"):
                if not m: continue
                ma, mb, mn = mspan.setdefault(host, {}).get(m, (t, t, 0))
                mspan[host][m] = (min(ma, t), max(mb, t), mn + 1)
        for host, (a, b, n) in span.items():
            yield (host, ports[host], a, b, n, mspan.get(host, {}))

    sidf, pf, mf = add_source("fofa-survey", "fofa/graflex", "struct_info", "fofa-live", fofa_rows(), True)
    sids, ps, ms = add_source("shodan-survey", "shodan/graflex", "banner", "shodan-live", shodan_rows(), False)
    sidp, pp, mp = add_source("live-probe", "graflex/daily", "api/tags", "probe-live", probe_rows(), True)
    c.executemany("INSERT INTO server(id,url,host,port,ip,ip_int,o1,o2) VALUES(?,?,?,?,?,?,?,?)", new_servers)
    c.executemany("INSERT INTO model(id,name,base,tag) VALUES(?,?,?,?)", new_models)
    con.commit()
    print(f"fofa-survey:   {pf} presence, {mf} model rows")
    print(f"shodan-survey: {ps} presence")
    print(f"live-probe:    {pp} presence, {mp} model rows")
    print(f"new servers: {len(new_servers)}  new models: {len(new_models)}")
    # coverage note
    ng = c.execute("SELECT COUNT(*) FROM server s WHERE s.id NOT IN (SELECT server_id FROM server_geo)"
                   " AND s.id >= ?", (min((r[0] for r in new_servers), default=10**9),)).fetchone()[0] if new_servers else 0
    print(f"new servers lacking geolocation: {len(new_servers)-(len(new_servers)-ng)} (need dbip CSV + geo.py to place on map)")
    con.close(); fc.close()

if __name__ == "__main__":
    main()
