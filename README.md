# woah…llama

Nineteen months of unsecured Ollama servers, reconstructed from the commit
histories of scanners that publish what they find, and extended with
point-in-time surveys and a daily re-probe of our own. The site reads it back
out as an interactive report in two chapters:

- **Chapter 1 — What's actually out there.** The survey of the real, open
  servers: geography (which labs' models each country runs), vendors and model
  lines over time, parameter size and quantisation, operator behaviour,
  coordinated block arrivals and departures, and how downloads compare with
  deployments.
- **Chapter 2 — Unexpected behavior.** Tens of thousands of hosts that answer
  the Ollama API from a fixed script: the same frozen model list everywhere,
  byte-identical sizes, rotating version strings, and chat replies assembled
  from a tiny phrase bank. What causes it is left open.

**Only Ollama.** Several of the captures cover other inference servers
(ComfyUI, vLLM, llama.cpp, LM Studio, Gradio, SGLang, A1111). Those are parsed
into the private staging database and go no further; nothing but
`service = ollama` reaches `survey.db` or any published number.

## Run it

The built site data is committed, so you can serve it immediately:

```sh
./serve.sh 8000     # then open http://localhost:8000
```

The page loads its data with `fetch()`, so it must be served rather than opened
as a file.

## Reproduce the data

```sh
./setup.sh          # clones the upstream scanners, fetches DB-IP, builds everything
```

`setup.sh` needs `git`, `python3` (standard library only), and `curl`. It clones
the three upstream repositories (their commit history is the dataset), downloads
the DB-IP city-lite database, ingests the git history into a run-length-encoded
SQLite database, and rebuilds `site/data/*.json`. Budget a few minutes and about
half a gigabyte of clones.

To rebuild only the derived data after `survey.db` exists:

```sh
./rebuild.sh
```

Every step that depends on a private capture skips cleanly when that capture is
absent, so a public checkout rebuilds the whole page from the two git scanners
alone.

## Where the data comes from

| source | how it is discovered | what it gives |
|---|---|---|
| `awesome-ollama-server` | GitHub Actions scanner, commits hourly since Feb 2025 | verified hosts, a real timeline |
| `ollamalist` | GitHub Actions scanner, accumulating list pruned every 4 days | verified hosts, a real timeline |
| `ollamaspider` | scrapes Shodan indiscriminately | the Chapter 2 population; kept out of the trend charts |
| `fofa-survey` | repeated FOFA scan runs | breadth, country and ASN, model catalogues |
| `shodan-survey` | Shodan result pages | a small point-in-time cross-check |
| `live-probe` | our own daily `/api/tags` re-probe | daemon **version**, country/ASN, and true day-to-day spans |

Only the two git scanners are public. The FOFA, Shodan and live-probe captures
are host-level data and are not in this repository.

## How the pipeline fits together

```
upstream scanners (git history)
        │  pipeline/ingest.py           run-length encode -> survey.db
        │  pipeline/geo_keep.py         carry server_geo across a full re-ingest
private captures
        │  pipeline/fofa_ingest.py      FOFA result pages   -> fofa/fofa.db
        │  pipeline/shodan_ingest.py    Shodan result pages -> fofa/fofa.db
        │  pipeline/graflex_daily.py    daily probe JSON    -> fofa/fofa.db
        │  pipeline/ingest_snapshot.py  merge those in as sources of survey.db
        │  pipeline/geo_from_capture.py country from the capture where DB-IP cannot
enrichment
        │  pipeline/vendors.py          model -> lab, lab HQ, model family, uncensored?
        │  pipeline/ollama_library.py   tag -> manifest digest -> real blob size
        │  pipeline/library_pulls.py    ollama.com pull counts and publish dates
        │  pipeline/ollama_releases.py  ollama/ git tags -> daemon release dates
        │  pipeline/model_releases.py   model-list.json -> model release dates
        │  pipeline/modelmeta.py        parameter count, size band, quantisation
        │  pipeline/clusters.py         identical-catalogue blocks
        │  pipeline/strange.py          the Chapter 2 analysis
        │  pipeline/questionable.py     per-machine flags from Chapter 2's tests
output
        └─ pipeline/build.py            survey.db -> site/data/*.json
           pipeline/build_pulls.py      downloads against deployments
           pipeline/build_lag.py        daemon release date against model age
           pipeline/survival_boot.py    censored-survival population estimate
                                        site/  static page, no dependencies
```

| file | what it is |
|---|---|
| `pipeline/gitblobs.py` | streams file revisions out of a repo via one `git cat-file --batch` |
| `pipeline/parse.py` | per-source parsers and URL canonicalisation |
| `pipeline/schema.sql` | the interval schema |
| `pipeline/mask.py` | redacts host identity for anything shipped publicly |
| `site/charts.js` | small SVG charting primitives, no dependencies |
| `site/app.js` | page wiring, map, scatter, canvas bubbles |

## Methodology

**Run-length encoding.** Consecutive snapshots are ~99.5% identical, so presence
is stored as intervals ("present in every snapshot from A to B"). Tens of
millions of observations compress to a few hundred thousand rows losslessly, and
a server that flaps produces several intervals rather than one smoothed span.

**Spans versus sightings.** A source that re-checks the same host on successive
days yields a genuine first-to-last span. A source that saw a host exactly once
does not: that is a censored observation, not a life that lasted zero days.
The lifespan and survival charts therefore take spans from the git scanners and
the live probe, and from FOFA only where repeated runs actually observed a host
on more than one day. Counting single sightings as zero-day servers would drag
every quantile toward nothing.

**Population estimates are survival estimates.** Sparse, irregular observation
means the raw count of servers seen in a month is a floor, not a population. The
population model treats the record as interval-censored and reports an estimate
with a confidence band that widens as coverage thins.

**Duplicate collapsing.** Groups of 50 or more addresses reporting an identical
model list on the same day are folded together for the "clean" series. That is a
claim about a snapshot. Chapter 2's `questionable` flag is separate and is a
claim about a machine; the two overlap far less than you would expect.

**`-cloud` tags are dropped** everywhere: they proxy to Ollama's hosted service
and commit no local weights, disk or GPU on the reporting machine.

**Closed-weights names do not count toward a lab.** A `claude-3-opus:latest` or
`gpt-4:latest` blob is not a model that lab shipped as weights, so those names
are excluded from vendor attribution while remaining visible everywhere else —
they are Chapter 2's subject matter. Community merges that merely mention a
commercial name keep their attribution.

**Lineages, not versions.** A base name pins one generation, so tracking base
names makes every series decay toward zero as its successor ships — an artefact
of the namespace growing, not operators walking away. `vendors.family` rolls a
generation into its line (gemma3 into gemma4, qwen3 into qwen3.6 and 3.8, llama3
into the muse models, and community re-uploads such as
`huihui_ai/qwen3.8-abliterated` back into Qwen), and the chart tracks that. It
excludes embedding models and the tiny demo models, which answer a different
question, along with Chapter 2's scratch and closed-weights names, which are not
a model line at all. With those out the lines move in both directions: Qwen rises
from 14.8% to 20.7% and passes Llama, while DeepSeek R falls from 22.9% to 9.3%.

**Downloads are not deployments.** ollama.com publishes a cumulative pull count
per model. It counts a different act from this survey, over a population three
orders of magnitude larger, so the two are only compared as shares of the same
universe. That count is also a non-expiring accumulator: it only goes up, so the
whole-library view is won by whatever has been there longest and nothing recent
can rank. Dividing by the model's age does not fix it, because the library
publishes a *last updated* stamp and for an old model that denominator is time
since its last re-push, unrelated to the window the pulls accumulated over. The
page instead offers a recency cohort, renormalising both sides over the models
refreshed in the last year. Measuring downloads *now* needs two readings of the
counter; `library_pulls.json` keeps one snapshot per fetch day and the delta view
turns on once a second exists.

**The responder fleet is measured as a share, not a count.** Counting
phantom-catalogue hosts on their own mostly tracks how hard the scanners were
working that month. As a fraction of everything visible on the same day the
coverage cancels, and what remains is a fleet that appeared in April 2025, peaked
at 9.6% of the exposed population that May, fell to 0.2% by January 2026, and has
climbed every month since to 11.5% — already larger than the first wave.

**"The company a model keeps" runs over time.** `build_hoarding_time.py` builds
monthly frames from survey.db, which is the source that has history — a different
population from the single-snapshot `hoarding.json` it sits next to, and Ollama
only. Axes are held fixed across frames so movement is the model moving. It also
records, per model per month, what share of that model's hosts are flagged by
Chapter 2, which is what separates the responder fleet's contribution from the
organic baseline.

**The hosting result is a positive claim; the rest are negative ones.**
`build_hosting.py` records both. Every phantom-catalogue host the FOFA capture
also saw is on AWS, and none of the 10,444 non-AWS hosts in the same capture is
one, where an even spread would put about 2,295 of them elsewhere. FOFA's Ollama
population is AWS-heavy to begin with, which is stated on the chart — but an
AWS-heavy sample does not yield exactly zero elsewhere. The negative results are
recorded the same way, from data rather than prose: the `ollama cp` examples in
every revision of Ollama's compatibility documentation (read out of the
repository's git history, which is what builds docs.ollama.com), against how often
those names actually appear in the wild. They do not match, and the file says so
with counts rather than assertion.

**The premium model names are a ransom note.** `build_campaigns.py` reads the
`/api/show` sweep and settles what Chapter 2 left open. Models named `gpt-4o`,
`claude-3-opus` and `gpt-4` are `tinyllama` with roughly 1.25 kB of extortion text
appended, installed through an Ollama API that accepted writes without
authentication. Ollama's own `parent_model` field says `tinyllama:latest` on 1,100
instances, and the GGUF architecture matches the real `tinyllama` on 362 hosts
that carry both. Three distinct payloads are present on 533 of 1,574 hosts, 104
of them carrying more than one, so several unrelated parties are writing to the
same machines. Only one asks for money. Its single Bitcoin address has received
nothing, verified against two independent block explorers that must agree before
the builder will publish a figure. The address is on the page on purpose, so that
somebody who finds the note on their own server and searches for it can see the
demand is a bluff. Nothing host-level is published, and `parent_model` paths are
dropped entirely because they carry the operator's OS username.

**The most recent two days are trimmed**, since a half-finished day of scanning
reads as a real drop in every trend.

## Notes on what the data can and can't say

- **Only aggregates are published.** This repository ships counts, shares, and
  distributions. It does not ship the list of reachable addresses; IPs in the
  site are masked to their /16, and the raw host-level captures are not included.
- **Geolocation is partial.** DB-IP places what it can from IP; hosts it cannot
  place fall back to the country the capture itself reported, which gives a
  country but no city or coordinates. Those hosts appear in the country mix and
  the choropleth and stay off the city bubble layer.
- **The version correlation covers the live probe only.** Only that source
  reports a daemon version, so "old daemons serving new models" is a statement
  about roughly two thousand machines, not about the whole survey.
- **Model release dates come from `model-list.json`**
  ([Artificial Analysis](https://artificialanalysis.ai/leaderboards/models)),
  not from ollama.com. The library's date is a *last updated* stamp: it is wrong
  by months, and it collapses separate releases onto one day, dating qwen3.5 and
  qwen3.6 to 2026-09-01 when they are six weeks apart. 42 of 179 models had
  provably been pulled onto an observed host before the date ollama.com gives.
  The catalogue only covers models notable enough to be benchmarked, so about
  half the observed model instances fall back to when they were first seen on a
  host — a rough lower bound, and one the version correlation refuses to use,
  since dating a model from the hosts running it and then comparing it against
  those hosts argues in a circle.
- **Chapter 2's tests go by model name**, so they are not clean: a community
  re-upload that keeps a commercial model's name gets swept up with the fakes.

IP geolocation by [DB-IP](https://db-ip.com) (CC BY 4.0). Model **release dates**
from [Artificial Analysis](https://artificialanalysis.ai/leaderboards/models),
via `model-list.json`. Model sizes and pull counts from
[ollama.com/library](https://ollama.com/library). Ollama daemon release dates
from the [ollama/ollama](https://github.com/ollama/ollama) tag history. Lab
attribution is by base-model lineage.
