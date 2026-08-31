#!/bin/sh
exec python3 "$(dirname "$0")/pipeline/serve.py" "${1:-8000}"
