#!/bin/sh
# Rebuild every derived artefact. Safe to re-run; the ollama.com scrape is cached
# in library_cache.json, so only new model names are fetched.
#
#   ./rebuild.sh [-s SURVEY_DIR] [-d DAILY_DIR] [LIBRARY_LIMIT]
#
#   -s  the graflex survey drop (<rundate>/ dirs, tags/)   default: tmp/graflex
#   -d  the graflex daily summaries (*.json)                default: graflex/
#
# The archives move depending on which machine the update runs from, so point at
# them here instead of copying them in. Both are only ever read.
set -e
usage() { echo "usage: $0 [-s survey_dir] [-d daily_dir] [library_limit]" >&2; exit 2; }
abspath() { (cd "$1" && pwd); }
while getopts s:d:h opt; do
  case $opt in
    s) [ -d "$OPTARG" ] || { echo "no such survey dir: $OPTARG" >&2; exit 1; }
       GRAFLEX_SURVEY=$(abspath "$OPTARG"); export GRAFLEX_SURVEY ;;
    d) [ -d "$OPTARG" ] || { echo "no such daily dir: $OPTARG" >&2; exit 1; }
       GRAFLEX_DAILY=$(abspath "$OPTARG"); export GRAFLEX_DAILY ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))
set -x
cd "$(dirname "$0")/pipeline"
SURVEY=${GRAFLEX_SURVEY:-../tmp/graflex}
DAILY=${GRAFLEX_DAILY:-../graflex}

# ---- merge the private point-in-time surveys into survey.db FIRST, so the model
# and vendor enrichment below sees their new model names. Each step skips cleanly
# when its private inputs are absent (a published checkout has neither). ----
if [ -d "$SURVEY" ]; then
  python3 fofa_ingest.py    >/dev/null 2>&1 && echo "  fofa ingest   ok" || true
  python3 shodan_ingest.py  >/dev/null 2>&1 && echo "  shodan ingest ok" || true
fi
if [ -d "$DAILY" ]; then
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
if [ -d "$SURVEY/tags" ]; then
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
python3 build_legit_share.py
# these read the survey drop's detail (FOFA ASN, /api/show sweep) for hosts the
# real sources already know; campaigns also asks two public block explorers
if [ -f ../fofa/fofa.db ]; then
  python3 build_hosting.py
  python3 build_campaigns.py || true
fi
# needs the private honeypot_probe capture; keeps the existing json without it
[ -d ../probe/honeypot_probe ] && python3 build_honeypot.py || true
if [ -f ../fofa/fofa.db ]; then
  python3 survival_boot.py >/dev/null && echo "  survival     ok"
fi
python3 geo_keep.py save
