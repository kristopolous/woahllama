#!/usr/bin/env python3
"""Attack-path probe: separate honeypots from real Ollama hosts.

A real Ollama daemon serves /api/tags and 404s everything else. A multi-protocol
honeypot answers 200 to whatever you ask for, including scanner bait like
/.git/config, /.env and /wp-login.php. This probes a sample of hosts with that
path set plus a random nonsense control, and writes one JSON line per host.

Raw output holds live host addresses and stays in probe/, which is gitignored.
Aggregates for the site are built by build_honeypot.py.

  python3 honeypot_probe.py phantom --frac 0.10
  python3 honeypot_probe.py control --n 500
"""
import argparse, hashlib, json, os, random, re, sqlite3, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(HERE, '..', 'survey.db')
OUT  = os.path.join(HERE, '..', 'probe', 'honeypot_probe')

# /api/tags first: it is the claim under test (does this answer as Ollama).
# The bait paths are what a scanner would ask for. The nonsense path separates a
# catch-all (200 to anything) from a curated kit (200 only to known bait).
PATHS = [
    ('api_tags',  '/api/tags'),
    ('git',       '/.git/config'),
    ('env',       '/.env'),
    ('wp',        '/wp-login.php'),
    ('mysql',     '/wp-content/mysql.sql'),
]
NONSENSE_LEN = 24
AKIA = re.compile(rb'AKIA[0-9A-Z]{16}')
BODY_CAP = 8192          # enough to fingerprint a template, not enough to hoard

_lock = threading.Lock()


def sample_phantom(frac, seed):
    """Phantom-catalogue hosts still being seen in the last two weeks."""
    db = sqlite3.connect(DB)
    urls = [r[0] for r in db.execute("""
        select s.url from server s
          join questionable_server q on q.server_id = s.id and q.phantom = 1
          join presence p on p.server_id = s.id
        where p.end_ts > (select max(end_ts) from presence) - 14*86400
        group by s.url""")]
    db.close()
    rnd = random.Random(seed)
    rnd.shuffle(urls)
    return urls[:max(1, round(len(urls) * frac))]


def sample_control(n, seed):
    """Verified-real Ollama hosts from the wider survey's working pool."""
    path = os.path.join(HERE, '..', 'ollama-working.json')
    rows = json.load(open(path))
    urls = sorted({r['url'].rstrip('/') for r in rows
                   if r.get('service') == 'ollama' and r.get('url')})
    rnd = random.Random(seed)
    rnd.shuffle(urls)
    return urls[:n]


def probe_one(url, timeout):
    """One host, one connection, every path. Returns a result dict."""
    nonsense = '/' + ''.join(random.Random(url).choices(
        'abcdefghijklmnopqrstuvwxyz0123456789', k=NONSENSE_LEN))
    out = {'url': url, 'checked': int(time.time()), 'paths': {}}
    s = requests.Session()
    s.mount('http://',  HTTPAdapter(max_retries=0))
    s.mount('https://', HTTPAdapter(max_retries=0))
    s.headers['User-Agent'] = 'Mozilla/5.0'
    try:
        for name, path in PATHS + [('nonsense', nonsense)]:
            try:
                r = s.get(url + path, timeout=timeout, verify=False,
                          allow_redirects=False, stream=True)
                body = r.raw.read(BODY_CAP, decode_content=True) or b''
                out['paths'][name] = {
                    'status': r.status_code,
                    'len':    len(body),
                    # body hash, so an identical kit across hosts is visible
                    # without keeping anyone's page content around
                    'sha1':   hashlib.sha1(body).hexdigest()[:16],
                    'akia':   len(set(AKIA.findall(body))),
                    'ctype':  (r.headers.get('content-type') or '')[:64],
                }
                if name == 'api_tags' and r.status_code == 200:
                    try:
                        out['models'] = sorted(
                            m['name'] for m in json.loads(body)['models'])[:40]
                    except Exception:
                        out['models'] = None
            except requests.RequestException as e:
                out['paths'][name] = {'error': type(e).__name__}
                if name == 'api_tags':
                    break               # host is down; no point asking for more
    finally:
        s.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('group', choices=['phantom', 'control'])
    ap.add_argument('--frac', type=float, default=0.10)
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--seed', type=int, default=20260910)
    ap.add_argument('--workers', type=int, default=48)
    ap.add_argument('--timeout', type=float, default=8.0)
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f'{a.group}.jsonl')
    done = set()
    if os.path.exists(dest):                     # --resume is the default
        for line in open(dest):
            try: done.add(json.loads(line)['url'])
            except Exception: pass

    urls = (sample_phantom(a.frac, a.seed) if a.group == 'phantom'
            else sample_control(a.n, a.seed))
    todo = [u for u in urls if u not in done]
    print(f'{a.group}: {len(urls)} sampled, {len(done)} already done, '
          f'{len(todo)} to probe', file=sys.stderr)

    fh = open(dest, 'a')
    n = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for res in ex.map(lambda u: probe_one(u, a.timeout), todo):
            with _lock:
                fh.write(json.dumps(res) + '\n'); fh.flush()
            n += 1
            if n % 50 == 0:
                print(f'  {n}/{len(todo)}', file=sys.stderr)
    fh.close()
    print(f'{a.group}: wrote {n} results to {dest}', file=sys.stderr)


if __name__ == '__main__':
    main()
