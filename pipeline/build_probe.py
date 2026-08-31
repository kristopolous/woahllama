"""Turn the raw probe captures in probe/ into site/data/probe.json.

Not part of the git-history pipeline: these are live captures the project owner
made by sending one instruction to every OllamaSpider host advertising a model,
then reading the replies. A genuine model gives the answer; the bogus fleet
replies with fixed madlibs filler that never does.

Two capture formats, because the method improved between runs:
  * chartreuse runs  - one flat file, hosts separated by dashed lines; a genuine
    reply is a line starting with the answer word.
  * washington run   - one file per host:port (the answer word cannot appear in
    the prompt, so a plain substring match is unambiguous).
"""
import glob, json, os, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOST = re.compile(r'^(\d{1,3}(?:\.\d{1,3}){3}:\d+)\s*$')
MADLIB = re.compile(r'regarding "|do my best to assist|here\'s what i can tell'
                    r'|let me think about this carefully|based on my understanding'
                    r'|great question|i\'d be happy to help', re.I)
REFUSE = re.compile(r"can't disclose|cannot assist|can't help|not able to|sorry", re.I)
CLOUD = re.compile(r'signed in to ollama|cloud models', re.I)


def classify(text, answer, line_start):
    low = text.lower()
    if not text.strip():
        return "silent"
    hit = (any(l.strip().lower().startswith(answer) for l in text.split("\n"))
           if line_start else answer in low)
    if hit:
        return "genuine"
    if CLOUD.search(low):
        return "cloud_stub"
    if MADLIB.search(low):
        return "canned"
    if REFUSE.search(low):
        return "refusal"
    return "canned"


def flat_run(path, model, answer, test):
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', raw)
    raw = re.sub(r'.\x08', '', raw)
    hosts, cur, buf = [], None, []
    for ln in raw.split("\n"):
        m = HOST.match(ln.strip())
        if m:
            if cur is not None:
                hosts.append((cur, "\n".join(buf)))
            cur, buf = m.group(1), []
        elif ln.strip() != "--------":
            buf.append(ln)
    if cur is not None:
        hosts.append((cur, "\n".join(buf)))
    return tally(hosts, model, answer, test, line_start=True)


def dir_run(d, model, answer, test):
    hosts = [(os.path.basename(f),
              pathlib.Path(f).read_text(encoding="utf-8", errors="replace"))
             for f in glob.glob(str(d / "*"))]
    return tally(hosts, model, answer, test, line_start=False)


def tally(hosts, model, answer, test, line_start):
    c = {"genuine": [], "silent": 0, "canned": 0, "cloud_stub": 0, "refusal": 0}
    for host, text in hosts:
        k = classify(text, answer, line_start)
        if k == "genuine":
            c["genuine"].append(host)
        else:
            c[k] += 1
    return {"model": model, "test": test, "probed": len(hosts),
            "genuine": len(c["genuine"]), "silent": c["silent"],
            "canned": c["canned"], "cloud_stub": c["cloud_stub"],
            "refusal": c["refusal"],
            # genuine_hosts kept in memory for the stable-IP count, never emitted
            "_genuine_hosts": sorted(c["genuine"])}


def main():
    P = ROOT / "probe"
    if not (P / "llama3_chartreuse_probe.txt").exists():
        print("  probe captures absent (private); keeping existing probe.json")
        return
    runs = [
        flat_run(P / "llama3_chartreuse_probe.txt", "llama3:latest", "chartreuse", "chartreuse"),
        flat_run(P / "qwen25_chartreuse_probe.txt", "qwen2.5:1.5b", "chartreuse", "chartreuse"),
        dir_run(P / "openchat_washington_probe", "openchat:7b", "washington", "first US president"),
    ]
    PROMPTS = {
        "chartreuse": "This is a test. Do not be conversational. "
                      "Respond with the word chartreuse.",
        "first US president": "This is test do not be conversational. "
                              "Repond with the name of the first United States President",
    }
    for r in runs:
        r["prompt"] = PROMPTS.get(r["test"], "")
    ips = lambda r: {h.split(":")[0] for h in r["_genuine_hosts"]}
    stable = set()
    for i in range(len(runs)):
        for j in range(i+1, len(runs)):
            stable |= ips(runs[i]) & ips(runs[j])
    # `ollama version` sent to the same hosts (user-supplied live-probe summary):
    # a real host reports one version; these rotate four fixed strings near-equally
    versions = {"note": "`ollama version` across the same hosts — four fixed strings "
                        "returned in near-equal proportion, from 0.1.0 to 0.6.3.",
                "counts": [["0.1.0", 161], ["0.1.20", 152],
                           ["0.1.34", 169], ["0.6.3", 183]]}
    for r in runs:
        r.pop("_genuine_hosts", None)
    out = {"population": "OllamaSpider hosts advertising the given model",
           "versions": versions,
           "stable_real_count": len(stable),
           "note": "A genuine model gives the answer; the bogus fleet replies with "
                   "fixed madlibs filler. Scoped to OllamaSpider's feed only.",
           "runs": runs}
    (ROOT / "site" / "data" / "probe.json").write_text(json.dumps(out, separators=(",", ":")))
    for r in runs:
        print(f"  {r['model']:16} {r['test']:20} {r['genuine']}/{r['probed']} "
              f"({100*r['genuine']/r['probed']:.1f}%)")
    print(f"  stable real IPs across probes: {len(stable)}")


if __name__ == "__main__":
    main()
