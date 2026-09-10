#!/bin/sh
# Rebuild every derived artefact. Safe to re-run; the ollama.com scrape is cached
# in library_cache.json, so only new model names are fetched.
set -ex
cd "$(dirname "$0")/pipeline"

# ---- merge the private point-in-time surveys into survey.db FIRST, so the model
# and vendor enrichment below sees their new model names. Each step skips cleanly
# when its private inputs are absent (a published checkout has neither). ----
if python3 -c "import graflex_paths,sys; sys.exit(0 if graflex_paths.root() else 1)"; then
  python3 fofa_ingest.py    >/dev/null 2>&1 && echo "  fofa ingest   ok" || true
  python3 shodan_ingest.py  >/dev/null 2>&1 && echo "  shodan ingest ok" || true
fi
if [ -d ../graflex ]; then
  python3 graflex_daily.py   >/dev/null 2>&1 && echo "  daily probe   ok" || true
fi
if [ -f ../fofa/fofa.db ]; then
  python3 ingest_snapshot.py >/dev/null && echo "  survey merge  ok"
fi
# server_geo cannot be regenerated without the db-ip CSV, and ingest.py drops it
# with the rest of survey.db. Re-attach the saved placements by URL before any
# chart reads them; a no-op when nothing was ever saved.
python3 geo_keep.py restore
# country from the capture itself for hosts the db-ip lookup cannot place
python3 geo_from_capture.py
if python3 -c "import graflex_paths,sys; sys.exit(0 if graflex_paths.root() else 1)"; then
  python3 build_tags.py >/dev/null && echo "  tag pull dates ok"   # writes site/data/fake_size.json
fi

python3 vendors.py         >/dev/null && echo "  vendors      ok"
python3 ollama_library.py "${1:-420}"
python3 modelmeta.py       >/dev/null && echo "  model meta   ok"
python3 clusters.py        >/dev/null && echo "  clusters     ok"
python3 spider_sizes.py    >/dev/null && echo "  spider sizes ok"
python3 strange.py
python3 questionable.py
# geolocate any new servers (needs the dbip city-lite CSV in pipeline/; if it is
# missing, existing server_geo is kept and new hosts stay off the map/country charts)
CSV=$(ls dbip-city-lite-*.csv.gz 2>/dev/null | tail -1 || true)
if [ -n "$CSV" ]; then python3 geo.py "$CSV" >/dev/null && echo "  geolocate    ok"; fi
python3 build.py
python3 build_probe.py
# the attack-path sweep that identifies the phantom fleet as honeypots
# (needs probe/honeypot_probe/; skips cleanly in a published checkout)
python3 build_honeypot.py
# ollama.com's advertised pull counts, cached per fetch day; the chart
# still builds from the last snapshot if the scrape fails or is offline
python3 library_pulls.py || true
python3 build_pulls.py
# daemon release dates need the ollama/ clone; model release dates need
# model-list.json. The chart skips cleanly without either.
python3 ollama_releases.py || true
python3 model_releases.py  || true
python3 build_lag.py || true
python3 survey_versions.py
python3 build_hoarding.py
python3 build_hoarding_time.py
# where the responder fleet is hosted + the negative results (needs fofa.db)
python3 build_hosting.py || true
# what the fake premium models are, and what the wallet earned (needs the
# /api/show sweep; queries two block explorers, skips cleanly offline)
python3 build_campaigns.py || true
if [ -f ../fofa/fofa.db ]; then
  python3 survival_boot.py >/dev/null && echo "  survival     ok"
fi
python3 geo_keep.py save
# the social card carries the headline numbers, so it is regenerated with them
python3 make_og.py
