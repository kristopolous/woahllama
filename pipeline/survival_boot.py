#!/usr/bin/env python3
"""Proper bootstrap uncertainty for the host survival model + population estimate.
Each replicate resamples the calibration cohort (KM sampling variance) AND draws a
tail half-life from a range (the structural tail assumption's uncertainty). Bands
are 2.5/97.5 percentiles across replicates. Writes site/data/population_model.json.
All inputs private; output is aggregate only."""
import os, json, sqlite3, datetime, glob
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "fofa", "fofa.db")
EPOCH = datetime.date(2025, 1, 1)
def od(s):
    try: return (datetime.date.fromisoformat((s or '')[:10]) - EPOCH).days
    except: return None

# ---------- gather per-host observations (ip:port) ----------
on, lon, off = {}, {}, {}
def so(h, dd):
    if h is None or dd is None: return
    if h not in on or dd < on[h]: on[h] = dd
    if h not in lon or dd > lon[h]: lon[h] = dd
def sf(h, dd):
    if h is None or dd is None: return
    if h not in off or dd < off[h]: off[h] = dd
for f in glob.glob(os.path.join(ROOT, "history", "*.jsonl")):
    for ln in open(f):
        r = json.loads(ln); so(r["host"], od(r["first_seen"])); so(r["host"], od(r["last_seen"]))
con = sqlite3.connect(DB); c = con.cursor()
for h, mt in c.execute("SELECT ip||':'||port, mtime FROM fofa_host WHERE mtime!=''"): so(h, od(mt))
for h, ts in c.execute("SELECT host, ts FROM shodan_host WHERE ts!=''"): so(h, od(ts))
for h, st, ck in c.execute("SELECT host, status, checked FROM probe WHERE checked!=''"):
    (so if st == 'working' else sf)(h, od(ck))
con.close()

hosts = list(on)
b   = np.array([on[h] for h in hosts], dtype=np.int32)       # birth (ordinal)
le  = np.array([lon[h] for h in hosts], dtype=np.int32)      # last online
ofd = np.array([off.get(h, -1) for h in hosts], dtype=np.int32)  # offline or -1

# calibration cohort: born in the robust dense-coverage window
W0, W1 = od("2025-04-01"), od("2025-09-30")
cal = (b >= W0) & (b <= W1)
cb, cle, coff = b[cal], le[cal], ofd[cal]
# per-cal-host observed duration + event(died?)
has_off = (coff > cle)
dur = np.where(has_off, coff - cb, np.where(cle < W1, cle - cb, W1 - cb)).astype(np.int64)
died = has_off | (cle < W1)
dur = np.clip(dur, 0, None)
NCAL = len(dur)

MAXD = 720
def km_lookup(idx):
    """KM on a (resampled) index set -> survival array S[0..MAXD], before tail decay."""
    d = dur[idx]; e = died[idx]
    order = np.argsort(d, kind='stable'); d = d[order]; e = e[order]
    n = len(d); S = 1.0; cur = 0
    arr = np.ones(MAXD + 1)
    # events grouped by time
    ut = np.unique(d)
    at_risk = n
    ptr = 0
    surv = {}
    for t in ut:
        mask = d == t
        de = int(e[mask].sum()); ce = int((~e[mask]).sum())
        if at_risk > 0 and de > 0:
            S *= (1 - de / at_risk)
        surv[t] = S
        at_risk -= (de + ce)
    # fill lookup as step function
    keys = sorted(surv); s = 1.0; ki = 0
    for t in range(MAXD + 1):
        while ki < len(keys) and keys[ki] <= t:
            s = surv[keys[ki]]; ki += 1
        arr[t] = s
    return arr

def apply_tail(arr, half):
    out = arr.copy()
    t = np.arange(MAXD + 1)
    m = t > 30
    out[m] = arr[30] * 0.5 ** ((t[m] - 30) / half)
    return out

# monthly grid ordinals (first of month, 2025-02 .. 2026-08)
months = []
y, mo = 2025, 2
while (y, mo) <= (2026, 8):
    months.append((datetime.date(y, mo, 1) - EPOCH).days); mo += 1
    if mo > 12: y += 1; mo = 1
Dm = np.array(months)
mlabels = []
y, mo = 2025, 2
while (y, mo) <= (2026, 8):
    mlabels.append(f"{y:04d}-{mo:02d}"); mo += 1
    if mo > 12: y += 1; mo = 1

age_le = np.clip(le - b, 0, MAXD)
age_off = np.where(ofd >= 0, np.clip(ofd - b, 0, MAXD), -1)

def population(Sd):
    """expected alive per month given survival lookup Sd."""
    base = Sd[age_le]                                  # S at last-online age
    out = np.zeros(len(Dm))
    for j, dm in enumerate(Dm):
        alive = (dm >= b) & (dm <= le)
        dead = (ofd >= 0) & (dm >= ofd)
        tail = (dm > le) & (~dead)
        age = np.clip(dm - b, 0, MAXD)
        s_age = Sd[age]
        contrib = alive.astype(float)
        idx = np.where(tail)[0]
        if len(idx):
            bs = base[idx]
            has = age_off[idx] >= 0
            p = np.zeros(len(idx))
            # no offline: conditional survival
            noff = ~has
            p[noff] = np.divide(s_age[idx][noff], bs[noff], out=np.zeros(noff.sum()), where=bs[noff] > 1e-9)
            # offline: bounded between last-online and offline
            if has.any():
                so_ = Sd[age_off[idx][has]]
                denom = bs[has] - so_
                num = s_age[idx][has] - so_
                p[has] = np.clip(np.divide(num, denom, out=np.zeros(has.sum()), where=denom > 1e-9), 0, 1)
            contrib[idx] = np.clip(p, 0, 1)
        out[j] = contrib.sum()
    return out

# observed raw distinct hosts seen online that month (from git+fofa+shodan online spans)
obs = np.zeros(len(Dm))
for j, dm in enumerate(Dm):
    obs[j] = int(((b <= dm) & (le >= dm) &
                  (b // 30 == b // 30)).sum())  # placeholder replaced below
# proper observed: seen online within +/-15d of month start (a real sighting that month)
# use last_online/first spans: count hosts whose observed online span covers the month start
obs = np.array([int(((b <= dm) & (le >= dm)).sum()) for dm in Dm])

# ---------- bootstrap ----------
rng = np.random.default_rng(42)
B = 300
pop_reps = np.zeros((B, len(Dm)))
surv_reps = np.zeros((B, 181))
tvals = np.arange(181)
for bi in range(B):
    idx = rng.integers(0, NCAL, NCAL)          # resample calibration cohort
    half = float(np.exp(rng.uniform(np.log(60), np.log(240))))  # tail half-life draw
    arr = km_lookup(idx)
    Sd = apply_tail(arr, half)
    pop_reps[bi] = population(Sd)
    surv_reps[bi] = Sd[tvals]

pop_med = np.median(pop_reps, axis=0)
pop_lo = np.percentile(pop_reps, 2.5, axis=0)
pop_hi = np.percentile(pop_reps, 97.5, axis=0)
sv_med = np.median(surv_reps, axis=0)
sv_lo = np.percentile(surv_reps, 2.5, axis=0)
sv_hi = np.percentile(surv_reps, 97.5, axis=0)
# median lifespan from median survival curve
med_life = int(next((t for t in tvals if sv_med[t] <= 0.5), 0))

out = {
    "months": mlabels,
    "estimate": [round(x) for x in pop_med],
    "lo": [round(x) for x in pop_lo],
    "hi": [round(x) for x in pop_hi],
    "observed": [int(x) for x in obs],
    "median_lifespan_days": med_life,
    "bootstrap": B,
    "survival": [[int(t), round(float(sv_med[t]), 4), round(float(sv_lo[t]), 4), round(float(sv_hi[t]), 4)]
                 for t in tvals],
}
p = os.path.join(ROOT, "site", "data", "population_model.json")
json.dump(out, open(p, "w"))
print(f"hosts={len(hosts)} calibration={NCAL} bootstrap={B}")
print(f"median lifespan (median curve): {med_life}d")
print(f"survival band examples: S(7)={sv_med[7]:.2f} [{sv_lo[7]:.2f}-{sv_hi[7]:.2f}]  S(30)={sv_med[30]:.2f} [{sv_lo[30]:.2f}-{sv_hi[30]:.2f}]")
print("month     observed   est   [lo - hi]   band_width")
for j, lab in enumerate(mlabels):
    print(f"  {lab}  {int(obs[j]):8}  {round(pop_med[j]):6} [{round(pop_lo[j])}-{round(pop_hi[j])}]  ±{round((pop_hi[j]-pop_lo[j])/2)}")
