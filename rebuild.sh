#!/bin/sh
# Rebuild every derived artefact. Safe to re-run; the ollama.com scrape is cached
# in library_cache.json, so only new model names are fetched.
set -e
cd "$(dirname "$0")/pipeline"
python3 vendors.py         >/dev/null && echo "  vendors      ok"
python3 ollama_library.py "${1:-420}"
python3 modelmeta.py       >/dev/null && echo "  model meta   ok"
python3 clusters.py        >/dev/null && echo "  clusters     ok"
python3 spider_sizes.py    >/dev/null && echo "  spider sizes ok"
python3 strange.py
python3 build.py
python3 build_probe.py
python3 survey_versions.py
python3 build_hoarding.py
