#!/usr/bin/env python3
"""Unify per-host observations across all four sources (git scanners, FOFA, Shodan,
probe) keyed on ip:port, then fit a Kaplan-Meier host-lifespan curve calibrated on
the robust git-coverage window (2025-04..2025-09). All private -> aggregates only."""
import os, json, sqlite3, datetime, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "fofa", "fofa.db")
DAY = datetime.date
def d(s):
    s = (s or '')[:10]
    try: return datetime.date.fromisoformat(s)
    except: return None

# ---- gather online sightings + offline marks per host (ip:port) ----
online = {}   # host -> earliest date seen online
last_on = {}  # host -> latest date seen online
offline = {}  # host -> earliest date confirmed offline

def see_online(host, dt):
    if not host or not dt: return
    if host not in online or dt < online[host]: online[host] = dt
    if host not in last_on or dt > last_on[host]: last_on[host] = dt
def see_offline(host, dt):
    if not host or not dt: return
    if host not in offline or dt < offline[host]: offline[host] = dt

# git scanners: span [first_seen, last_seen] both online
for f in glob.glob(os.path.join(ROOT, "history", "*.jsonl")):
    for ln in open(f):
        r = json.loads(ln)
        see_online(r["host"], d(r["first_seen"])); see_online(r["host"], d(r["last_seen"]))
# fofa + shodan + probe from db
con = sqlite3.connect(DB); c = con.cursor()
for host, mt in c.execute("SELECT ip||':'||port, mtime FROM fofa_host WHERE mtime!=''"):
    see_online(host, d(mt))
for host, ts in c.execute("SELECT host, ts FROM shodan_host WHERE ts!=''"):
    see_online(host, d(ts))
for host, st, ck in c.execute("SELECT host, status, checked FROM probe WHERE checked!=''"):
    (see_online if st == 'working' else see_offline)(host, d(ck))

hosts = set(online) | set(offline)
print(f"unified hosts (ip:port) across all sources: {len(hosts)}")

# ---- Kaplan-Meier on robust window ----
W0, W1 = DAY(2025,4,1), DAY(2025,9,30)
obs = []   # (duration_days, died?)
for h in online:
    b = online[h]
    if not (W0 <= b <= W1):        # calibrate only on hosts born in the robust window
        continue
    lo = last_on[h]
    off = offline.get(h)
    # death observed if we have an offline mark, OR it vanished before window end
    if off and off > lo:
        death = lo + (off - lo)/2 if False else off   # conservative: died by offline mark
        dur = (off - b).days; died = True
    elif lo < W1:                  # disappeared while git coverage still dense -> died ~last_on
        dur = (lo - b).days; died = True
    else:                          # still present at window end -> right-censored
        dur = (W1 - b).days; died = False
    if dur >= 0: obs.append((dur, died))

obs.sort()
n = len(obs); atrisk = n; S = 1.0
surv = [(0, 1.0)]
import collections
# group by duration
from itertools import groupby
i = 0
km = []
times = sorted(set(t for t,_ in obs))
at_risk = n
for t in times:
    deaths = sum(1 for dd,ev in obs if dd==t and ev)
    censor = sum(1 for dd,ev in obs if dd==t and not ev)
    if at_risk>0 and deaths>0:
        S *= (1 - deaths/at_risk)
    km.append((t, S, at_risk, deaths))
    at_risk -= (deaths+censor)

def surv_at(days):
    s = 1.0
    for t,sv,ar,de in km:
        if t<=days: s=sv
        else: break
    return s
# median lifespan
med = next((t for t,sv,ar,de in km if sv<=0.5), None)
print(f"KM calibration hosts (born {W0}..{W1}): {n}  (deaths observed: {sum(1 for _,e in obs if e)})")
print(f"median lifespan: {med} days" if med else "median lifespan: > observed range (S never hit 0.5)")
for dd in (7,14,30,60,90,120,180):
    print(f"  S({dd:3}d) = P(still up) = {surv_at(dd):.2f}")
con.close()

# ================= population-over-time estimate via survival sampling =================
def build_population():
    import math, json as _json
    def d(s):
        try: return datetime.date.fromisoformat((s or '')[:10])
        except: return None
    W0,W1=datetime.date(2025,4,1),datetime.date(2025,9,30)
    on={}; lon={}; off={}
    def so(h,dt):
        if h and dt:
            if h not in on or dt<on[h]: on[h]=dt
            if h not in lon or dt>lon[h]: lon[h]=dt
    def sf(h,dt):
        if h and dt and (h not in off or dt<off[h]): off[h]=dt
    for f in glob.glob(os.path.join(ROOT,"history","*.jsonl")):
        for ln in open(f):
            r=_json.loads(ln); so(r["host"],d(r["first_seen"])); so(r["host"],d(r["last_seen"]))
    con=sqlite3.connect(DB); c=con.cursor()
    for h,mt in c.execute("SELECT ip||':'||port,mtime FROM fofa_host WHERE mtime!=''"): so(h,d(mt))
    for h,ts in c.execute("SELECT host,ts FROM shodan_host WHERE ts!=''"): so(h,d(ts))
    for h,st,ck in c.execute("SELECT host,status,checked FROM probe WHERE checked!=''"):
        (so if st=='working' else sf)(h,d(ck))
    con.close()
    # KM with Greenwood CI, calibrated on robust-window births
    obs=[]
    for h in on:
        b=on[h]
        if not (W0<=b<=W1): continue
        lo=lon[h]; o=off.get(h)
        if o and o>lo: dur=(o-b).days; ev=True
        elif lo<W1: dur=(lo-b).days; ev=True
        else: dur=(W1-b).days; ev=False
        if dur>=0: obs.append((dur,ev))
    n=len(obs); times=sorted(set(t for t,_ in obs))
    S=1.0; varsum=0.0; km=[]
    ar=n
    for t in times:
        de=sum(1 for dd,e in obs if dd==t and e); ce=sum(1 for dd,e in obs if dd==t and not e)
        if ar>0 and de>0:
            S*=(1-de/ar); varsum+=de/(ar*(ar-de)) if ar>de else 0
        se=S*math.sqrt(varsum) if S>0 else 0
        km.append((t,S,max(0,S-1.96*se),min(1,S+1.96*se))); ar-=(de+ce)
    def S3raw(days):
        pt=lo_=hi=1.0
        for t,s,l,h_ in km:
            if t<=days: pt,lo_,hi=s,l,h_
            else: break
        return pt,lo_,hi
    # Finite tail: past 30d the KM plateau is right-censoring, not immortality.
    # Decay it with a 120-day half-life so long-unseen persistent hosts fade out.
    HALF=120.0
    def S3(days):
        if days<=30: return S3raw(days)
        p,l,h=S3raw(30); f=0.5**((days-30)/HALF)
        return p*f,l*f,h*f
    # monthly grid
    months=[]; y,m=2025,2
    while (y,m)<=(2026,8):
        months.append(datetime.date(y,m,1)); m+=1
        if m>12: y+=1; m=1
    est=[0.0]*len(months); lo_b=[0.0]*len(months); hi_b=[0.0]*len(months); raw=[0]*len(months)
    for h in on:
        b=on[h]; le=lon[h]; o=off.get(h)
        Sb_pt,Sb_lo,Sb_hi = S3((le-b).days)  # survival at last-online (conditioning point)
        for i,md in enumerate(months):
            if md<b: continue
            if md<=le:
                est[i]+=1; lo_b[i]+=1; hi_b[i]+=1; raw[i]+=1; continue
            if o and md>=o: continue           # known dead
            age=(md-b).days
            sp,sl,sh=S3(age)
            # conditional survival past last-online; cap denom
            def cond(s,base): return min(1.0, s/base) if base>0 else 0.0
            if o:   # dead by o: bound the tail
                so_pt,so_lo,so_hi=S3((o-b).days)
                denom=Sb_pt-so_pt
                p = (sp-so_pt)/denom if denom>1e-9 else 0.0
                est[i]+=max(0,min(1,p))
                lo_b[i]+=max(0,min(1,(sl-so_hi)/((Sb_lo-so_hi) or 1e-9)))
                hi_b[i]+=max(0,min(1,(sh-so_lo)/((Sb_hi-so_lo) or 1e-9)))
            else:
                est[i]+=cond(sp,Sb_pt); lo_b[i]+=cond(sl,Sb_pt); hi_b[i]+=cond(sh,Sb_pt)
    med=next((t for t,s,l,h_ in km if s<=0.5),None)
    out={"months":[md.isoformat()[:7] for md in months],
         "estimate":[round(x) for x in est],"lo":[round(x) for x in lo_b],"hi":[round(x) for x in hi_b],
         "observed":raw,"median_lifespan_days":med,
         "survival":[[t,round(s,4),round(l,4),round(h_,4)] for t,s,l,h_ in km if t<=180]}
    os.makedirs(os.path.join(ROOT,"site","data"),exist_ok=True)
    p=os.path.join(ROOT,"site","data","population_model.json")
    _json.dump(out,open(p,"w"))
    print("\nwrote",p)
    print("month   observed  est[lo-hi]")
    for i,md in enumerate(months):
        print(f"  {md.isoformat()[:7]}  {raw[i]:7}   {round(est[i]):6} [{round(lo_b[i])}-{round(hi_b[i])}]")

if __name__=="__main__":
    build_population()
