#!/usr/bin/env python3
"""'The company a model keeps', as a timeline rather than one snapshot.

For each model: how many hosts run it, and how large is the library of a typical
host that does. The existing hoarding.json answers that for a single
point-in-time capture of the wider survey. This answers it once a month across
the whole record, which is what makes it useful next to the responder-fleet
waves - a model whose hosts suddenly all carry the same six-model library is a
different thing from a model sitting on ordinary varied machines.

Source is survey.db, not the private wider-survey snapshot, because survey.db is
the one with history. That means this is Ollama only and covers a different
population from hoarding.json; the two are not interchangeable and the chart says
which it is showing. `-cloud` tags are dropped, per the standing rule, and hosts
are counted once per model per frame.

Writes site/data/hoarding_time.json."""
import collections, datetime, json, pathlib, sqlite3, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
EXCLUDE_SOURCES = {"ollamaspider"}
MIN_HOSTS = 12          # below this a mean library size is noise
CUTOFF_DAYS = 2
DAY = 86400

sys.path.insert(0, str(ROOT / "pipeline"))
from vendors import vendor as vendor_of, is_uncensored, family as family_of
from mask import mask_model_name


def month_frames(lo, hi):
    """The 15th of each month covered by the record. Mid-month avoids the
    month-boundary scanning gaps that would otherwise thin a frame."""
    out = []
    d = datetime.datetime.fromtimestamp(lo, datetime.UTC).replace(
        day=15, hour=12, minute=0, second=0, microsecond=0)
    if d.timestamp() < lo:
        d = (d.replace(day=28) + datetime.timedelta(days=8)).replace(day=15, hour=12)
    end = datetime.datetime.fromtimestamp(hi, datetime.UTC)
    while d < end:
        out.append(d)
        d = (d.replace(day=28) + datetime.timedelta(days=8)).replace(day=15, hour=12)
    return out


def main():
    con = sqlite3.connect(ROOT / "survey.db")
    lo, hi = con.execute("SELECT min(start_ts), max(end_ts) FROM presence").fetchone()
    hi -= CUTOFF_DAYS * DAY
    sources = {i: n for i, n in con.execute("SELECT id,name FROM source")
               if n not in EXCLUDE_SOURCES}
    keep = "(" + ",".join(str(i) for i in sources) + ")"

    cloud = {r[0] for r in con.execute(
        "SELECT model_id FROM model_meta WHERE is_cloud=1")}
    questionable = {r[0] for r in con.execute(
        "SELECT server_id FROM questionable_server")}
    base_of = dict(con.execute("SELECT id,base FROM model"))
    params = {}
    for mid, pb in con.execute(
            "SELECT model_id, params_b FROM model_meta WHERE params_b IS NOT NULL"):
        b = base_of.get(mid)
        if b and (b not in params or pb > params[b]):
            params[b] = pb

    frames = month_frames(lo, hi)
    fmeta, series = [], collections.defaultdict(dict)
    for fi, f in enumerate(frames):
        ts = int(f.timestamp())
        cat = collections.defaultdict(set)
        for sv, mid in con.execute(
                f"SELECT server_id,model_id FROM server_model"
                f" WHERE source_id IN {keep} AND start_ts<=? AND end_ts>=?", (ts, ts)):
            if mid not in cloud:
                b = base_of.get(mid)
                if b:
                    cat[sv].add(b)
        if not cat:
            continue
        sizes = [len(v) for v in cat.values()]
        by = collections.defaultdict(list)
        flagged = collections.Counter()
        for sv, v in cat.items():
            n = len(v)
            for b in v:
                by[b].append(n)
                if sv in questionable:
                    flagged[b] += 1
        fmeta.append({
            "date": f.date().isoformat(),
            "hosts": len(cat),
            "mean_lib": round(sum(sizes) / len(sizes), 2),
        })
        k = len(fmeta) - 1
        for b, s in by.items():
            if len(s) >= MIN_HOSTS:
                series[b][k] = [len(s), round(sum(s) / len(s), 2),
                                round(100 * flagged[b] / len(s))]

    # ---- the aggregate: the whole record pooled into one view ---------------
    # Each server's library is every distinct model it was ever seen running, and
    # a model's number is the mean of that over the servers that ever ran it.
    # This is the all-time answer the monthly frames are a decomposition of, and
    # it is what the chart shows before you press play.
    ever = collections.defaultdict(set)
    for sv, mid in con.execute(
            f"SELECT DISTINCT server_id, model_id FROM server_model"
            f" WHERE source_id IN {keep}"):
        if mid not in cloud:
            b = base_of.get(mid)
            if b:
                ever[sv].add(b)
    agg_by, agg_flag = collections.defaultdict(list), collections.Counter()
    for sv, v in ever.items():
        n = len(v)
        for b in v:
            agg_by[b].append(n)
            if sv in questionable:
                agg_flag[b] += 1
    agg_sizes = [len(v) for v in ever.values()]
    overall = {
        "hosts": len(ever),
        "mean_lib": round(sum(agg_sizes) / len(agg_sizes), 2) if agg_sizes else 0,
        "models": {},
    }

    models = {}
    for b, pts in series.items():
        if not pts:
            continue
        # mask the derived labels too, not just the key: family() falls back to
        # the model's own name, so an IP-shaped model name would ride out in the
        # value even with the key masked
        safe = mask_model_name(b)
        models[safe] = {
            "vendor": mask_model_name(vendor_of(b)),
            "family": mask_model_name(family_of(b)),
            "params": params.get(b),
            "uncensored": 1 if is_uncensored(b) else 0,
            # [frame, hosts, mean library, % of those hosts flagged questionable]
            "points": [[k, *v] for k, v in sorted(pts.items())],
        }
        a = agg_by.get(b)
        if a and len(a) >= MIN_HOSTS:
            overall["models"][safe] = [len(a), round(sum(a) / len(a), 2),
                                       round(100 * agg_flag[b] / len(a))]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hoarding_time.json").write_text(json.dumps(
        {"frames": fmeta, "models": models, "overall": overall,
         "min_hosts": MIN_HOSTS},
        separators=(",", ":")))
    print(f"  hoarding_time.json  {len(fmeta)} monthly frames + aggregate, "
          f"{len(models)} models (>= {MIN_HOSTS} hosts in at least one frame)")
    print(f"    all-time    {overall['hosts']:6} hosts  mean library "
          f"{overall['mean_lib']}  {len(overall['models'])} models")
    for m in (fmeta[0], fmeta[len(fmeta)//2], fmeta[-1]):
        print(f"    {m['date']}  {m['hosts']:6} hosts  mean library {m['mean_lib']}")
    con.close()


if __name__ == "__main__":
    main()
