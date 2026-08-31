#!/bin/sh
# Rebuild every derived artefact. Safe to re-run; the ollama.com scrape is cached
# in library_cache.json, so only new model names are fetched.
set -e
cd "$(dirname "$0")/pipeline"

# ---- merge the private point-in-time surveys into survey.db FIRST, so the model
# and vendor enrichment below sees their new model names. Each step skips cleanly
# when its private inputs are absent (a published checkout has neither). ----
if [ -d ../tmp/graflex ]; then
  python3 fofa_ingest.py    >/dev/null 2>&1 && echo "  fofa ingest   ok" || true
  python3 shodan_ingest.py  >/dev/null 2>&1 && echo "  shodan ingest ok" || true
fi
if [ -f ../fofa/fofa.db ]; then
  python3 ingest_snapshot.py >/dev/null && echo "  survey merge  ok"
fi
if [ -d ../tmp/graflex/tags ]; then
  python3 build_tags.py >/dev/null && echo "  tag pull dates ok"   # writes site/data/fake_size.json
fi

python3 vendors.py         >/dev/null && echo "  vendors      ok"
python3 ollama_library.py "${1:-420}"
python3 modelmeta.py       >/dev/null && echo "  model meta   ok"
python3 clusters.py        >/dev/null && echo "  clusters     ok"
python3 spider_sizes.py    >/dev/null && echo "  spider sizes ok"
python3 strange.py
# geolocate any new servers (needs the dbip city-lite CSV in pipeline/; if it is
# missing, existing server_geo is kept and new hosts stay off the map/country charts)
CSV=$(ls dbip-city-lite-*.csv.gz 2>/dev/null | tail -1 || true)
if [ -n "$CSV" ]; then python3 geo.py "$CSV" >/dev/null && echo "  geolocate    ok"; fi
python3 build.py
python3 build_probe.py
python3 survey_versions.py
python3 build_hoarding.py
if [ -f ../fofa/fofa.db ]; then
  python3 survival_boot.py >/dev/null && echo "  survival     ok"
fi
