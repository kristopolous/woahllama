"""Per-source parsers and URL/model normalisation.

Each parser takes the raw bytes of one revision and returns
{canonical_url: [model_name, ...]}.  Canonicalising the URL is what lets the
three sources be compared: they write the same host three different ways
(`http://ip:11434`, `http://ip:11434/v1`, `https://host` with an implicit port).
"""
import csv, io, ipaddress, json, re

DEFAULT_PORT = {"http": 80, "https": 443}
_URL = re.compile(r"^(?P<scheme>https?)://(?P<host>[^/:]+|\[[^\]]+\])(?::(?P<port>\d+))?")


def canon_url(raw):
    """-> (canonical_url, host, port, ip, ip_int) or None if unparseable."""
    m = _URL.match(raw.strip())
    if not m:
        return None
    scheme, host = m.group("scheme"), m.group("host")
    port = int(m.group("port")) if m.group("port") else DEFAULT_PORT[scheme]
    ip = ip_int = None
    try:
        addr = ipaddress.ip_address(host)
        if addr.version == 4:
            ip, ip_int = str(addr), int(addr)
    except ValueError:
        pass  # a hostname, not a literal IP
    return (f"{scheme}://{host}:{port}", host, port, ip, ip_int)


def split_model(name):
    base, _, tag = name.rpartition(":")
    return (base, tag) if base else (name, "")


def _add(out, url, models):
    """Merge into the snapshot dict, unioning models if the URL repeats."""
    seen = out.setdefault(url, [])
    have = set(seen)
    for m in models:
        if m not in have:
            have.add(m)
            seen.append(m)


# --- Awesome-Ollama-Server: public/data.json -------------------------------
# [{"server": "http://ip:11434", "models": [...], "tps": 0,
#   "lastUpdate": "...", "status": "success"}]   (status added mid-2025)
def parse_aos(blob):
    out = {}
    for e in json.loads(blob):
        if e.get("status", "success") != "success":
            continue
        u = canon_url(e.get("server", ""))
        if u:
            _add(out, u, (m for m in e.get("models") or [] if m))
    return out


# --- ollamalist: output_with_models.csv ------------------------------------
# url,"model, model"    with a `host,models` header only in the first weeks
def parse_ollamalist(blob):
    out = {}
    text = blob.decode("utf-8", "replace")
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0] or row[0] == "host":
            continue
        u = canon_url(row[0])
        if not u:
            continue
        models = row[1] if len(row) > 1 else ""
        _add(out, u, (m.strip() for m in models.split(",") if m.strip()))
    return out


# --- OllamaSpider: url_models.json -----------------------------------------
# [{"url": "http://ip:11434", "models": [{"name": ..., "size": ...}]}]
def parse_spider(blob):
    out = {}
    for e in json.loads(blob):
        u = canon_url(e.get("url", ""))
        if not u:
            continue
        _add(out, u, (m["name"] for m in e.get("models") or [] if m.get("name")))
    return out


SOURCES = [
    dict(name="awesome-ollama-server", repo="Awesome-Ollama-Server",
         path="public/data.json", discovery="fofa (US,CN,JP,KR,SG,TW only)",
         parse=parse_aos),
    dict(name="ollamalist", repo="ollamalist",
         path="output_with_models.csv", discovery="accumulated list, pruned every 4d",
         parse=parse_ollamalist),
    dict(name="ollamaspider", repo="OllamaSpider",
         path="url_models.json", discovery="shodan",
         parse=parse_spider),
]
