"""Parse a FOFA results HTML (Nuxt devalue blob) into asset dicts."""
import re, json

def deref_pool(pool):
    def deref(i, depth=0):
        if not isinstance(i, int) or i < 0 or i >= len(pool): return i
        if depth > 14: return None
        v = pool[i]
        if isinstance(v, dict):
            return {k: deref(x, depth+1) for k, x in v.items()}
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("ShallowReactive","Reactive","Ref","EmptyRef"):
                return deref(v[1], depth+1)
            return [deref(x, depth+1) for x in v]
        return v
    return deref

def assets(path):
    html = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(r'id="__NUXT_DATA__">(.*?)</script>', html, re.S)
    if not m: return []
    pool = json.loads(m.group(1))
    root = deref_pool(pool)(1)
    data = root.get('data', {})
    keys = [k for k in data if k.startswith('result-search-assets')]
    if not keys: return []
    d = data[keys[0]].get('data') or {}
    return d.get('assets') or []
