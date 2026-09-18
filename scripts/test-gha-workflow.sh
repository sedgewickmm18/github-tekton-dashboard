#!/usr/bin/env bash
# ==============================================================================
# test-gha-workflow.sh
#
# Simulates the GitHub Actions workflow (.github/workflows/pages.yml) locally:
# 1. Verifies prerequisites (Python, uv, Node, npm).
# 2. Runs the scraper in SQLite mode writing directly to web-spa/public/dashboard.db
#    (or seeds a mock SQLite database if credentials are not configured or --mock is passed).
# 3. Installs web-spa dependencies and builds the static SPA bundle (npm run build).
# 4. Asserts that all GitHub Pages deployment artifacts exist and are valid.
# 5. Optionally serves a local preview server (--preview).
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_step() {
  echo -e "\n${BLUE}==>${NC} ${GREEN}$1${NC}"
}

log_warn() {
  echo -e "${YELLOW}WARNING:${NC} $1"
}

log_error() {
  echo -e "${RED}ERROR:${NC} $1" >&2
}

# Parse options
MODE="auto" # auto | mock | live
PREVIEW=false
DAYS="${SCRAPER_DAYS:-30}"

for arg in "$@"; do
  case "$arg" in
    --mock)
      MODE="mock"
      ;;
    --live)
      MODE="live"
      ;;
    --preview)
      PREVIEW=true
      ;;
    --help|-h)
      echo "Usage: ./scripts/test-gha-workflow.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --mock      Force generating/using synthetic SQLite data without calling IBM Cloud API"
      echo "  --live      Force live scraper execution (fails if credentials in pipeline.env are missing)"
      echo "  --preview   Start a local preview server on completion to inspect the built SPA"
      echo "  --help, -h  Show this help message"
      exit 0
      ;;
    *)
      log_warn "Unknown option: $arg"
      ;;
  esac
done

cd "${ROOT_DIR}"

# ------------------------------------------------------------------------------
# Step 1: Verify tools and environment
# ------------------------------------------------------------------------------
log_step "Step 1: Checking local tools (mimicking GitHub Actions runner setup)"

command -v uv >/dev/null 2>&1 || {
  log_error "'uv' is required. Install via: curl -Ls https://astral.sh/uv/install.sh | sh"
  exit 1
}

command -v node >/dev/null 2>&1 || {
  log_error "'node' is required. Install Node.js 18+"
  exit 1
}

command -v npm >/dev/null 2>&1 || {
  log_error "'npm' is required."
  exit 1
}

echo "✓ uv $(uv --version)"
echo "✓ node $(node --version)"
echo "✓ npm $(npm --version)"

# ------------------------------------------------------------------------------
# Step 2: Run Tekton Scraper in SQLite mode (or Mock DB)
# ------------------------------------------------------------------------------
log_step "Step 2: Preparing SQLite database (web-spa/public/dashboard.db)"

mkdir -p "${ROOT_DIR}/web-spa/public"
SQLITE_TARGET="${ROOT_DIR}/web-spa/public/dashboard.db"

has_valid_credentials() {
  local env_file="${ROOT_DIR}/scraper/pipeline.env"
  if [ -n "${IBM_CLOUD_API_KEY:-}" ] && [ -n "${PIPELINE_ID:-}" ]; then
    return 0
  fi
  if [ -f "$env_file" ]; then
    local key pid
    key=$(grep -E "^IBM_CLOUD_API_KEY=" "$env_file" | cut -d= -f2- | tr -d ' "[:space:]')
    pid=$(grep -E "^PIPELINE_ID=" "$env_file" | cut -d= -f2- | tr -d ' "[:space:]')
    if [ -n "$key" ] && [ -n "$pid" ]; then
      return 0
    fi
  fi
  return 1
}

create_mock_db() {
  log_step "Creating synthetic SQLite fixture at ${SQLITE_TARGET} for workflow test..."
  rm -f "${SQLITE_TARGET}"
  python3 - <<EOF
import sqlite3
import datetime

con = sqlite3.connect("${SQLITE_TARGET}")
cur = con.cursor()

# Schema
cur.executescript("""
CREATE TABLE IF NOT EXISTS pipelines (
    pipeline_id  TEXT PRIMARY KEY,
    name         TEXT,
    region       TEXT,
    trigger_name TEXT
);

CREATE TABLE IF NOT EXISTS prs (
    pr_number  INTEGER PRIMARY KEY,
    title      TEXT,
    author     TEXT,
    url        TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    pipeline_id      TEXT,
    pr_number        INTEGER,
    build_number     INTEGER,
    status           TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    duration_seconds REAL,
    commit_sha       TEXT,
    pr_author        TEXT
);

CREATE TABLE IF NOT EXISTS run_stages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status    TEXT,
    reason    TEXT,
    UNIQUE(run_id, stage_name)
);

CREATE TABLE IF NOT EXISTS run_errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    error_type TEXT NOT NULL,
    UNIQUE(run_id, error_type)
);

CREATE TABLE IF NOT EXISTS reruns (
    run_id         TEXT NOT NULL,
    prev_run_id    TEXT NOT NULL,
    rerun_type     TEXT,
    wasted_seconds REAL DEFAULT 0.0,
    PRIMARY KEY (run_id, prev_run_id)
);

CREATE TABLE IF NOT EXISTS scrape_meta (
    key              TEXT PRIMARY KEY,
    last_scraped_at  TEXT,
    run_count        INTEGER,
    days             INTEGER,
    pipeline_url     TEXT,
    github_repo_url  TEXT
);
""")

now = datetime.datetime.now(datetime.timezone.utc)
now_iso = now.isoformat()
yesterday_iso = (now - datetime.timedelta(days=1)).isoformat()

# Seed pipeline
cur.execute("INSERT INTO pipelines VALUES ('mock-pipeline-001', 'Demo Pipeline', 'us-south', 'pr-trigger')")

# Seed PRs
cur.execute("INSERT INTO prs VALUES (101, 'Fix auth token refresh', 'alice', 'https://github.com/org/repo/pull/101', ?)", (yesterday_iso,))
cur.execute("INSERT INTO prs VALUES (102, 'Add metrics endpoint', 'bob', 'https://github.com/org/repo/pull/102', ?)", (yesterday_iso,))

# Seed Runs
cur.execute("INSERT INTO runs VALUES ('run-01', 'mock-pipeline-001', 101, 1, 'failed', ?, ?, 420.0, 'a1b2c3d', 'alice')", (yesterday_iso, yesterday_iso))
cur.execute("INSERT INTO runs VALUES ('run-02', 'mock-pipeline-001', 101, 2, 'succeeded', ?, ?, 380.0, 'a1b2c3d', 'alice')", (now_iso, now_iso))
cur.execute("INSERT INTO runs VALUES ('run-03', 'mock-pipeline-001', 102, 1, 'succeeded', ?, ?, 310.0, 'e5f6g7h', 'bob')", (now_iso, now_iso))

# Seed Stages
cur.execute("INSERT INTO run_stages (run_id, stage_name, status, reason) VALUES ('run-01', 'pr-code-build', 'failed', 'Unit test failed')")
cur.execute("INSERT INTO run_stages (run_id, stage_name, status, reason) VALUES ('run-02', 'pr-code-build', 'succeeded', 'Pass')")
cur.execute("INSERT INTO run_stages (run_id, stage_name, status, reason) VALUES ('run-03', 'pr-code-build', 'succeeded', 'Pass')")

# Seed Errors
cur.execute("INSERT INTO run_errors (run_id, error_type) VALUES ('run-01', 'Unit test failure: auth_test')")

# Seed Reruns
cur.execute("INSERT INTO reruns VALUES ('run-02', 'run-01', 'same_sha', 420.0)")

# Seed Meta
cur.execute("INSERT INTO scrape_meta VALUES ('latest', ?, 3, 30, 'https://cloud.ibm.com', 'https://github.com/org/repo')", (now_iso,))

con.commit()
con.close()
print("✓ Synthetic test database seeded successfully.")
EOF
}

if [ "$MODE" = "mock" ]; then
  create_mock_db
elif [ "$MODE" = "live" ] || has_valid_credentials; then
  echo "Running scraper with TEKTON_BACKEND=sqlite and TEKTON_SQLITE_PATH=${SQLITE_TARGET}..."
  (
    cd "${ROOT_DIR}/scraper"
    export TEKTON_BACKEND="sqlite"
    export TEKTON_SQLITE_PATH="${SQLITE_TARGET}"
    uv run python -m tekton_scraper.main --days "${DAYS}"
  )
else
  log_warn "No live IBM Cloud credentials detected in scraper/pipeline.env or environment."
  log_warn "Falling back to synthetic fixture for testing build & SPA workflow."
  create_mock_db
fi

# Assert DB exists
if [ ! -s "${SQLITE_TARGET}" ]; then
  log_error "Expected SQLite database at ${SQLITE_TARGET} was not created or is empty!"
  exit 1
fi
echo "✓ SQLite database ready: $(ls -lh "${SQLITE_TARGET}")"

# ------------------------------------------------------------------------------
# Step 3: Install web-spa dependencies and build
# ------------------------------------------------------------------------------
log_step "Step 3: Building web SPA (npm run build inside web-spa/)"

cd "${ROOT_DIR}/web-spa"
if [ ! -d "node_modules" ]; then
  echo "Installing web-spa dependencies..."
  npm install
fi

npm run build

# ------------------------------------------------------------------------------
# Step 4: Verification / Artifact Assertion
# ------------------------------------------------------------------------------
log_step "Step 4: Validating generated deployment artifacts"

DIST_DIR="${ROOT_DIR}/web-spa/dist"

assert_file_exists() {
  local f="$1"
  if [ ! -s "${DIST_DIR}/${f}" ]; then
    log_error "Missing required distribution artifact: ${DIST_DIR}/${f}"
    exit 1
  fi
  echo "✓ Found: ${f} ($(ls -lh "${DIST_DIR}/${f}" | awk '{print $5}'))"
}

assert_file_exists "index.html"
assert_file_exists "dashboard.db"
assert_file_exists "sql-wasm.wasm"

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN} SUCCESS: GitHub Actions workflow simulation passed! ${NC}"
echo -e "${GREEN} All static assets and SQLite DB verified in dist/  ${NC}"
echo -e "${GREEN}======================================================${NC}"

# ------------------------------------------------------------------------------
# Step 5: Optional preview
# ------------------------------------------------------------------------------
if [ "$PREVIEW" = true ]; then
  log_step "Step 5: Starting local preview server (Press Ctrl+C to stop)..."
  cd "${ROOT_DIR}/web-spa"
  npm run preview
fi
