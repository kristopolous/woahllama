#!/usr/bin/env python3
"""Reconstruct a per-host historical inventory from EVERY commit of the three
scanner repos, straight from git blobs (no survey.db, no build.py). Output is
private (real IP:PORT) and lives under ./history/ which is gitignored."""
import subprocess, json, re, datetime, collections, sys, os, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IPRE = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+)')

def hostof(url):
    m = IPRE.search(url or '')
    return m.group(1) if m else None

def parse_aos(b):
    for o in json.loads(b):
        h = hostof(o.get('server'))
        if h: yield h, o.get('models') or []

def parse_spider(b):
    for o in json.loads(b):
        h = hostof(o.get('url'))
        if h: yield h, [m.get('name') for m in (o.get('models') or []) if isinstance(m, dict)]

def parse_csv(b):
    for line in b.decode('utf-8','replace').splitlines():
        if not line.startswith('http'): continue
        url, _, rest = line.partition(',')
        h = hostof(url)
        if h:
            models = [m.strip().strip('"') for m in rest.strip().strip('"').split(',') if m.strip()]
            yield h, models

SOURCES = [
    ("aos",    "Awesome-Ollama-Server", "public/data.json",         parse_aos),
    ("ollama", "ollamalist",            "output_with_models.csv",   parse_csv),
    ("spider", "OllamaSpider",          "url_models.json",          parse_spider),
]

def commits(repo, path):
    out = subprocess.run(["git","-C",repo,"log","--format=%H %ct","--",path],
                         capture_output=True, text=True, cwd=ROOT).stdout
    for ln in out.splitlines():
        h, ts = ln.split()
        yield h, int(ts)

def batch_blobs(repo, specs):
    """specs: list of (rev, ts). Yields (ts, bytes) via a single cat-file --batch."""
    p = subprocess.Popen(["git","-C",repo,"cat-file","--batch"], cwd=ROOT,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    # Feed stdin from a separate thread so we can read stdout concurrently;
    # writing all specs before reading deadlocks once both pipes fill.
    def _feed():
        for r, _ in specs:
            p.stdin.write(f"{r}\n".encode())
        p.stdin.close()
    threading.Thread(target=_feed, daemon=True).start()
    for _, ts in specs:
        header = p.stdout.readline().decode().split()
        if len(header) < 3:      # missing object
            continue
        size = int(header[2])
        buf = bytearray()
        while len(buf) < size:
            chunk = p.stdout.read(size - len(buf))
            if not chunk: break
            buf += chunk
        p.stdout.read(1)  # trailing \n
        yield ts, bytes(buf)
    p.wait()

for key, repo, path, parser in SOURCES:
    specs = [(f"{h}:{path}", ts) for h, ts in commits(repo, path)]
    seen = {}   # host -> [first_ts, last_ts, set(dates), last_ts_for_models, models]
    ncommits = 0
    for ts, blob in batch_blobs(repo, specs):
        ncommits += 1
        day = datetime.datetime.fromtimestamp(ts, datetime.UTC).strftime('%Y-%m-%d')
        try:
            rows = list(parser(blob))
        except Exception:
            continue
        for host, models in rows:
            r = seen.get(host)
            if r is None:
                seen[host] = [ts, ts, {day}, ts, models]
            else:
                r[0] = min(r[0], ts); r[2].add(day)
                if ts >= r[1]: r[1] = ts
                if ts >= r[3]: r[3] = ts; r[4] = models
    outp = os.path.join(ROOT, "history", f"{key}.jsonl")
    with open(outp, "w") as f:
        for host,(ft,lt,days,_,models) in sorted(seen.items(),
                key=lambda kv: kv[1][0]):
            f.write(json.dumps({
                "host": host,
                "first_seen": datetime.datetime.fromtimestamp(ft, datetime.UTC).strftime('%Y-%m-%d'),
                "last_seen":  datetime.datetime.fromtimestamp(lt, datetime.UTC).strftime('%Y-%m-%d'),
                "days_seen":  len(days),
                "last_models": models,
            })+"\n")
    print(f"{key:7} commits={ncommits:5}  unique_hosts={len(seen):6}  -> history/{key}.jsonl")
