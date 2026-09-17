#!/usr/bin/env bash
# Thin wrapper for crontab.
# Example crontab entry:
#   0 6 * * * /path/to/scraper/run_scraper.sh >> /var/log/tekton-scraper.log 2>&1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
uv run python -m tekton_scraper.main --days "${SCRAPER_DAYS:-30}" --env pipeline.env
