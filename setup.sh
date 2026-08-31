#!/bin/sh
# Reproduce the dataset from scratch. Needs: git, python3 (stdlib only), curl.
set -e
cd "$(dirname "$0")"

echo "[1/4] cloning the three upstream scanners (their commit history is the data)"
clone() { [ -d "$2" ] || git clone "https://github.com/$1" "$2"; }
clone forrany/Awesome-Ollama-Server Awesome-Ollama-Server
clone hcshi/ollamalist              ollamalist
clone wangyuxinwhy/OllamaSpider     OllamaSpider

echo "[2/4] fetching the DB-IP city-lite database (CC BY 4.0)"
CSV="pipeline/dbip-city-lite-$(date +%Y-%m).csv.gz"
if [ ! -f "$CSV" ]; then
  curl -fSL -o "$CSV" "https://download.db-ip.com/free/$(basename "$CSV")" || {
    echo "  this month's file may not be published yet."
    echo "  download any dbip-city-lite-YYYY-MM.csv.gz into pipeline/ and re-run."; exit 1; }
fi

echo "[3/4] ingesting git history into survey.db (~4 minutes)"
( cd pipeline && python3 ingest.py && python3 geo.py "../$CSV" )

echo "[4/4] building the site data"
./rebuild.sh

echo
echo "done.  ./serve.sh 8000   then open http://localhost:8000"
