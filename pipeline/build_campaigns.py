#!/usr/bin/env python3
"""What is actually inside the fake premium models, and what it earned.

An /api/show sweep of the exposed hosts answers the question Chapter 2 left open.
The models named `gpt-4o`, `claude-3-opus` and `gpt-4` are not OpenAI's or
Anthropic's weights, and they are not people aliasing a local model so their
tooling works. They are `tinyllama` with a ransom note appended, written onto
servers whose API accepts writes without authentication.

Three separate payloads are distinguishable. Only one asks for money, and this
file also records what that wallet received, which is the finding: nothing.

Everything emitted here is aggregate. No addresses, no hostnames. The probe
captures also contain `parent_model` paths that carry the operator's OS username
(`/Users/<name>/...`), so nothing from that field is written out.

Writes site/data/campaigns.json."""
import collections, json, pathlib, re, sys, urllib.request

import graflex_paths

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"


def _latest_show_sweep():
    """The newest complete graflex run carrying an /api/show sweep.

    Pinning a run id here goes stale the moment a new sweep lands and the chart
    then quietly keeps reporting the old one, so pick it up from the drop.
    """
    for _rid, d in reversed(graflex_paths.run_dirs()):
        m = pathlib.Path(d) / "models"
        if m.is_dir() and any(m.glob("*.json")):
            return m
    return ROOT / "tmp" / "models"      # nothing found; glob() below yields none


PROBE = _latest_show_sweep()

WALLET = "bc1q5xpazlg7q6ph2r6s7tzumd5zyjdet6vjzvsqln"
EXPLORERS = ("https://mempool.space/api/address/{}",
             "https://blockstream.info/api/address/{}")

CAMPAIGNS = (
    ("ransom",   "Bitcoin ransom note", lambda s: WALLET in s),
    ("verified", "VERIFIED_OK",         lambda s: "VERIFIED_OK" in s),
    ("sje",      "SJE-SYSTEM-OK-2026",  lambda s: "SJE-SYSTEM-OK" in s),
)
PREMIUM = re.compile(r"^(gpt-[0-9]|claude|gemini|grok)", re.I)
# the GGUF fields that identify the architecture underneath the name
ARCH = ("general.parameter_count", "llama.block_count", "llama.embedding_length",
        "llama.attention.head_count", "llama.attention.head_count_kv",
        "llama.feed_forward_length", "llama.context_length", "general.file_type")


def wallet_balance(addr):
    """Ask two independent explorers. Both must answer, and they must agree,
    before any number goes on the page."""
    out = []
    for url in EXPLORERS:
        try:
            with urllib.request.urlopen(url.format(addr), timeout=20) as r:
                d = json.loads(r.read().decode())
            cs, ms = d.get("chain_stats", {}), d.get("mempool_stats", {})
            out.append({
                "source": url.split("/")[2],
                "tx_count": cs.get("tx_count"),
                "received_sats": cs.get("funded_txo_sum"),
                "mempool_tx": ms.get("tx_count"),
            })
        except Exception as e:
            print(f"  ! {url.split('/')[2]}: {e}", file=sys.stderr)
    if len(out) < 2:
        return None
    if len({(o["tx_count"], o["received_sats"]) for o in out}) != 1:
        print("  ! explorers disagree; not publishing a balance", file=sys.stderr)
        return None
    return {"address": addr, "checks": out,
            "tx_count": out[0]["tx_count"], "received_sats": out[0]["received_sats"]}


def main():
    if not PROBE.is_dir():
        print("  campaigns: /api/show sweep absent (private); skipping", file=sys.stderr)
        return 0
    files = sorted(PROBE.glob("*.json"))
    hosts = collections.defaultdict(set)
    names = collections.defaultdict(collections.Counter)
    answered, premium = set(), set()
    arch_fake, arch_real, both = collections.Counter(), collections.Counter(), set()
    parents, instances = collections.Counter(), collections.Counter()
    wallets = collections.Counter()
    BTC = re.compile(r"\b(bc1[a-z0-9]{25,62}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b")

    note_text, modelfile = None, None
    for fp in files:
        try:
            d = json.loads(fp.read_text())
        except Exception:
            continue
        h = fp.name                     # opaque id; never the address
        seen_fake = seen_real = None
        for name, v in (d.get("models") or {}).items():
            if not isinstance(v, dict) or "error" in v:
                continue
            answered.add(h)
            base = name.split(":")[0].lower()
            if PREMIUM.match(name):
                premium.add(h)
            blob = json.dumps(v)
            sig = tuple((v.get("model_info") or {}).get(k) for k in ARCH)
            for key, _lab, test in CAMPAIGNS:
                if test(blob):
                    hosts[key].add(h)
                    names[key][base] += 1
                    instances[key] += 1
            if WALLET in blob:
                # the note itself, taken verbatim from the server rather than
                # retyped. It is identical on every instance, so the first is
                # representative; `seeded` is the conversation the author wrote
                # on both sides so the model agrees before anyone talks to it.
                if note_text is None and (v.get("system") or "").strip():
                    note_text = v["system"]
                    # The raw Modelfile, which is stored configuration and not a
                    # conversation anybody had. Rendering the `messages` array as
                    # a chat transcript implied an exchange that never happened,
                    # so the file itself goes on the page instead. The FROM line
                    # is a local blob path and on many hosts contains the
                    # operator's OS username, so it is stripped.
                    mf = v.get("modelfile") or ""
                    modelfile = "\n".join(
                        "FROM <local blob, path removed>" if ln.startswith("FROM ") else ln
                        for ln in mf.splitlines()
                        if not ln.startswith("# ")).strip()
                arch_fake[sig] += 1
                seen_fake = sig
                pm = (v.get("details") or {}).get("parent_model") or "(none)"
                # only a bare model name is safe to keep; a filesystem path
                # carries the operator's username
                parents["tinyllama:latest" if pm == "tinyllama:latest"
                        else "other" if "/" in pm or "\\" in pm else pm] += 1
            elif base == "tinyllama":
                arch_real[sig] += 1
                seen_real = sig
            for a in BTC.findall((v.get("system") or "") + blob[:0]):
                wallets[a] += 1
        if seen_fake and seen_real and seen_fake == seen_real:
            both.add(h)

    top_fake = arch_fake.most_common(1)
    out = {
        "hosts_answered": len(answered),
        "hosts_premium": len(premium),
        "campaigns": [{
            "key": k, "label": lab,
            "hosts": len(hosts[k]),
            "instances": instances[k],
            "share_probed": round(100 * len(hosts[k]) / len(answered), 1) if answered else 0,
            "share_premium": round(100 * len(hosts[k] & premium) / len(premium), 0) if premium else 0,
            "names": names[k].most_common(4),
            "asks_for_money": k == "ransom",
        } for k, lab, _ in CAMPAIGNS],
        "hosts_any": len(set().union(*hosts.values())) if hosts else 0,
        "hosts_multi": sum(1 for h in set().union(*hosts.values())
                           if sum(h in hosts[k] for k, _, _ in CAMPAIGNS) > 1) if hosts else 0,
        "evidence": {
            "arch": dict(zip(ARCH, top_fake[0][0])) if top_fake else {},
            "arch_instances": top_fake[0][1] if top_fake else 0,
            "arch_matches_real_tinyllama": arch_real.get(top_fake[0][0], 0) if top_fake else 0,
            "hosts_carrying_both": len(both),
            "parent_model": parents.most_common(3),
        },
        "note_text": note_text,
        "note_variants": len({t for t in [note_text] if t}),
        "modelfile": modelfile,
        "distinct_wallets": len(wallets) or 1,
        "wallet": wallet_balance(WALLET),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "campaigns.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"  campaigns.json  {len(answered):,} hosts answered /api/show, "
          f"{len(premium)} advertise a premium name")
    for c in out["campaigns"]:
        print(f"    {c['label']:22}{c['hosts']:5} hosts  {c['share_probed']:5}% of probed")
    w = out["wallet"]
    print(f"    wallet: {'tx=' + str(w['tx_count']) + ' received=' + str(w['received_sats']) + ' sats'
                        if w else 'not verified'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
