"""Map model names to the organisation that trained the base model.

Vendor is a more legible axis than model id and survives naming churn: qwen2.5
-> qwen3 -> qwen3.6 is one story about Alibaba, not three about three models.

Matching runs against the last path segment, so community re-uploads land with
their base model's vendor (`hf.co/unsloth/Qwen3-Coder-Next` -> Alibaba,
`huihui_ai/deepseek-r1-abliterated` -> DeepSeek).  Rules are ordered; the first
hit wins, so more specific patterns come first.  A fine-tune whose name no
longer names its lineage (`dolphin3`) stays "Community/other" rather than being
guessed at.
"""
import re

RULES = [
    ("probe", r"probe-nonexistent|academic_research_probe|^probe$"),
    ("Alibaba (Qwen)",   r"qwen|qwq|qvq|tongyi|marco-o1|\bgte[-_]|^gte$"),
    ("DeepSeek",         r"deepseek"),
    ("Meta (Llama)",     r"codellama|llama-guard|llamaguard|\bllama\b|^llama|llama\d|llava|bakllava"),
    ("Microsoft (Phi)",  r"^phi|-phi|\bphi\d|bitnet|wizardlm|orca(?!-mini-v)"),
    ("Google (Gemma)",   r"gemma|gemini|t5gemma|paligemma|medgemma"),
    ("Mistral AI",       r"mistral|mixtral|codestral|devstral|ministral|magistral|pixtral|mathstral"),
    ("Cohere",           r"^command|command-|aya[-:]|^aya$"),
    ("OpenAI",           r"gpt-oss|^gpt|chatgpt"),
    ("IBM (Granite)",    r"granite"),
    ("NVIDIA",           r"nemotron|nvidia"),
    ("Zhipu (GLM)",      r"^glm|chatglm|codegeex"),
    ("Hugging Face (SmolLM)", r"smollm|smolvlm|zephyr"),
    ("BAAI",             r"\bbge\b|^bge|bge-"),
    ("Nomic",            r"nomic-embed"),
    ("Mixedbread",       r"mxbai"),
    ("Moonshot (Kimi)",  r"^kimi|kimi-"),
    ("01.AI (Yi)",       r"^yi[-:]|^yi$|yi-coder"),
    ("Baidu (ERNIE)",    r"ernie"),
    ("Tencent",          r"hunyuan"),
    ("ByteDance",        r"^seed-|doubao"),
    ("xAI (Grok)",       r"grok"),
    ("Allen AI",         r"olmo|molmo|tulu"),
    ("TII (Falcon)",     r"falcon"),
    ("Upstage (Solar)",  r"^solar"),
    ("LG (EXAONE)",      r"exaone"),
    ("OpenBMB",          r"minicpm"),
    ("Shanghai AI Lab",  r"internlm|internvl"),
    ("Reka",             r"reka"),
    ("AI21 (Jamba)",     r"jamba"),
    ("Snowflake",        r"^arctic"),
    ("Databricks",       r"dbrx"),
    ("Stability AI",     r"stable-?(lm|code|diffusion)"),
    ("BigCode",          r"starcoder|santacoder"),
    ("Nous Research",    r"hermes|^nous"),
    ("Sentence-Transf.", r"all-minilm|paraphrase-|multilingual-e5|^e5-"),
    ("Anthropic",        r"claude"),
    ("Moondream",        r"moondream"),
    ("OpenChat",         r"openchat"),
    ("LMSYS (Vicuna)",   r"vicuna"),
    ("Cognitive Comp.",  r"^dolphin"),
    ("TinyLlama",        r"tinyllama"),
]
COMPILED = [(v, re.compile(p, re.I)) for v, p in RULES]

# Names that advertise removed guardrails or adult roleplay.  Only explicit
# self-description counts - a model is not called uncensored here because of
# what it can be made to do, but because its publisher labelled it that way.
UNCENSORED = re.compile(
    r"abliterat|uncensor|lorablated|amoral|unfiltered|nsfw|deepsex|erotic|"
    r"adult-film|pygmalion|unalign|jailbreak|dolphin|darkest-muse|dark-?idol|"
    r"nolimit|heretic", re.I)


# Where the lab that trained the base model is headquartered. This is the axis
# that actually varies between countries - every other slice is dominated by
# "how many servers are here" and renders as a population map.
ORIGIN = {
    "Meta (Llama)": "US", "Google (Gemma)": "US", "Microsoft (Phi)": "US",
    "OpenAI": "US", "IBM (Granite)": "US", "NVIDIA": "US", "Allen AI": "US",
    "Databricks": "US", "Snowflake": "US", "Nous Research": "US",
    "Cognitive Comp.": "US", "LMSYS (Vicuna)": "US", "Moondream": "US",
    "Reka": "US", "OpenChat": "US", "Sentence-Transf.": "US",
    "Nomic": "US", "xAI (Grok)": "US", "Anthropic": "US", "BigCode": "US",

    "Alibaba (Qwen)": "CN", "DeepSeek": "CN", "Zhipu (GLM)": "CN",
    "Moonshot (Kimi)": "CN", "Tencent": "CN", "Baidu (ERNIE)": "CN",
    "ByteDance": "CN", "01.AI (Yi)": "CN", "OpenBMB": "CN",
    "Shanghai AI Lab": "CN", "BAAI": "CN",

    "Mistral AI": "EU", "Hugging Face (SmolLM)": "EU", "Stability AI": "EU",
    "Mixedbread": "EU", "Aleph Alpha": "EU",

    "LG (EXAONE)": "KR", "Upstage (Solar)": "KR",
    "TII (Falcon)": "AE", "AI21 (Jamba)": "IL", "Cohere": "CA",
    "TinyLlama": "SG",
}


def origin(vendor_label):
    return ORIGIN.get(vendor_label, "other")


def is_uncensored(name):
    return bool(UNCENSORED.search(name))


def vendor(base):
    """Classify a model base name (no tag) to a vendor label."""
    tail = base.rsplit("/", 1)[-1]
    for label, rx in COMPILED:
        if rx.search(tail) or rx.search(base):
            return label
    return "Community/other"


if __name__ == "__main__":
    import sqlite3, pathlib, collections
    con = sqlite3.connect(pathlib.Path(__file__).resolve().parent.parent / "survey.db")
    con.execute("DROP TABLE IF EXISTS model_vendor")
    con.execute("CREATE TABLE model_vendor(model_id INTEGER PRIMARY KEY, vendor TEXT)")
    rows = [(i, vendor(b)) for i, b in con.execute("SELECT id, base FROM model")]
    con.executemany("INSERT INTO model_vendor VALUES(?,?)", rows)
    con.execute("CREATE INDEX model_vendor_v ON model_vendor(vendor)")
    con.commit()
    tot = collections.Counter()
    for v, n in con.execute("""SELECT mv.vendor, count(DISTINCT sm.server_id)
            FROM server_model sm JOIN model_vendor mv ON mv.model_id=sm.model_id
            GROUP BY mv.vendor ORDER BY 2 DESC"""):
        tot[v] = n
    for v, n in tot.most_common(24):
        print(f"  {v:22} {n:7} servers")
    unk = [b for b, in con.execute("""SELECT DISTINCT m.base FROM model m
            JOIN model_vendor mv ON mv.model_id=m.id WHERE mv.vendor='Community/other'
            ORDER BY m.id LIMIT 25""")]
    print("\n  unclassified sample:", unk[:14])


# ---------------------------------------------------------------- families ---
# A model's base name pins a generation, not a line: gemma3 is superseded by
# gemma4, qwen3 by qwen3.5 and 3.6 and 3.8, llama3 by the muse models. Tracking
# bases alone makes every series decay toward zero as its successor takes over,
# which reads as "people are abandoning these models" when the mass has actually
# moved one name to the right. The family is the line, so the two together say
# whether a lineage is growing while a generation within it fades.
#
# Curated first, because the naming is not systematic enough to infer: `qwen2.5`
# and `qwen3` are the same line, `qwen2.5-coder` is a different one, and
# `deepseek-r1` versus `deepseek-v3` are separate lines that share a prefix.
# `V` is the generation suffix every one of these names carries in some form:
# gemma3, qwen2.5, phi4-mini, glm-5.2, llama3.2-vision. Matching it once here
# keeps the rules about the *line* rather than about punctuation.
V = r"(?:[-.]?\d[\d.]*)"

FAMILY_RULES = [
    # more specific lines first: a coder or vision variant is its own line, not
    # a generation of the base model
    ("Qwen coder",     rf"^qwen{V}?-?coder"),
    ("Qwen VL",        rf"^qwen{V}?-?(vl|omni)"),
    ("Qwen",           rf"^qwen{V}?$|^qwq{V}?$|^qvq{V}?$"),
    ("Code Llama",     r"^codellama"),
    ("TinyLlama",      r"^tinyllama"),
    ("Llama vision",   rf"^llama{V}-vision"),
    ("Llama (Meta)",   rf"^llama{V}?$|^llama-guard|^muse($|{V}|-)"),
    ("CodeGemma",      r"^codegemma"),
    ("Gemma",          rf"^gemma{V}?$|^shieldgemma"),
    ("DeepSeek R",     r"^deepseek-r\d"),
    ("DeepSeek coder", r"^deepseek-coder"),
    ("DeepSeek V",     r"^deepseek-v\d"),
    ("Mistral",        rf"^mistral{V}?$|^mixtral|^ministral|^mistral-(nemo|small|large|openorca)"),
    ("Phi",            rf"^phi{V}?$|^phi{V}?-(mini|small|medium|vision|reasoning)"),
    ("GLM",            rf"^glm{V}?$|^chatglm|^codegeex"),
    ("GPT-OSS",        r"^gpt-oss"),
    ("Granite",        rf"^granite{V}?$|^granite{V}?-(code|vision|moe|dense)"),
    ("Nemotron",       r"^nemotron|^llama3[.\d]*-nemotron"),
    ("Command",        r"^command-"),
    ("SmolLM",         rf"^smollm{V}?$"),
    ("Embeddings",     r"embed|^bge-|^e5-|^gte-|^snowflake-arctic-embed"),
    # a hf.co/<user>/<repo> name is one community upload, not a lineage; they
    # would otherwise each become their own single-member "family"
    ("Hugging Face direct", r"^hf\.co/|^huggingface\.co/"),
    ("LLaVA / vision", r"^llava|^bakllava|^moondream|^minicpm-v"),
]
FAMILY_COMPILED = [(v, re.compile(p, re.I)) for v, p in FAMILY_RULES]

# strip a trailing generation number from an otherwise unmatched name, so
# `ornith-1.5` and `ornith` land together without needing a rule each
_GEN = re.compile(r"^(.*?)[-_]?\d+(\.\d+)*$")


def family(base):
    """The model line a base name belongs to. Falls back to the name with any
    trailing generation number removed, and finally to the name itself."""
    b = (base or "").strip().lower()
    if not b:
        return ""
    for label, rx in FAMILY_COMPILED:
        if rx.search(b):
            return label
    m = _GEN.match(b)
    stem = m.group(1) if m and len(m.group(1)) >= 3 else b
    return stem
