# Tekton Pipeline Dashboard

A reactive desktop dashboard for IBM Cloud Tekton pipeline analytics.  
Python scraper → FalkorDB **or SQLite** → Tauri + Svelte frontend.

## Architecture

```
scraper/          Python uv project — fetches IBM Cloud Tekton data, writes to DB
  collectors/     Pure function modules (fetch, analyze, stage detection, reruns…)
  db/             Backend-agnostic writer + FalkorDB / SQLite implementations
  main.py         Orchestrator entry point (with tqdm progress bars)
  cleanup_pipeline.py  Delete data for a specific pipeline ID
  run_scraper.sh  Cron-friendly shell wrapper

dashboard/        Tauri v2 desktop app
  src/            Svelte frontend (App, stores, pages)
  src-tauri/      Rust backend — Tauri commands backed by FalkorDB or SQLite
```

## Storage backends

Both the scraper and the dashboard support **FalkorDB** (graph database) and
**SQLite** (local file).  The same two-step logic is applied independently in
each process:

```
TEKTON_BACKEND=sqlite    → always use SQLite, no probe attempted
TEKTON_BACKEND=falkordb  → always use FalkorDB, hard-fail if unreachable
(not set)                → TCP probe localhost:6379 with 1.5 s timeout
                              reachable   → FalkorDB
                              unreachable → SQLite  (~/.tekton-dashboard.db)
```

The decision is made **once per process** and cached for its lifetime (Python
`@lru_cache`, Rust `OnceLock`).

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `TEKTON_BACKEND` | *(auto)* | Force `sqlite` or `falkordb`; omit for auto-detect |
| `FALKORDB_HOST` | `localhost` | FalkorDB hostname |
| `FALKORDB_PORT` | `6379` | FalkorDB port |
| `FALKORDB_GRAPH` | `tekton-dashboard` | Graph name inside FalkorDB |
| `TEKTON_SQLITE_PATH` | `~/.tekton-dashboard.db` | SQLite file path |

### When to use each

| | FalkorDB | SQLite |
|-|----------|--------|
| **Setup** | Requires Docker / separate process | Zero setup — file created automatically |
| **Query language** | Cypher (graph) | SQL |
| **Persistence across restarts** | Survives container restarts with a volume | Always persists |
| **Recommended for** | Teams, CI, long-term history | Local / single-user usage |

Start FalkorDB with Docker and the scraper/dashboard will pick it up automatically:

```bash
docker run -d --name falkordb -p 6379:6379 falkordb/falkordb
```

Stop the container and both processes fall back to SQLite on next launch.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------| 
| Python | 3.11+ | [python.org](https://python.org) |
| uv | latest | `curl -Ls https://astral.sh/uv/install.sh \| sh` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |
| Rust + Cargo | 1.77+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Tauri CLI | 2.x | installed via `npm install` in `dashboard/` |
| FalkorDB | latest | *optional* — `docker run -p 6379:6379 falkordb/falkordb` |

## Quick Start

### 1. (Optional) Start FalkorDB

```bash
docker run -d --name falkordb -p 6379:6379 falkordb/falkordb
```

Skip this step to use SQLite automatically.

### 2. Configure the scraper

```bash
cp scraper/pipeline.env.example scraper/pipeline.env
# Edit pipeline.env with your IBM Cloud credentials
```

Required fields in `scraper/pipeline.env`:

```ini
IBM_CLOUD_API_KEY=<your-api-key>
PIPELINE_ID=<tekton-pipeline-uuid>
REGION=us-south
TRIGGER_NAME=pr-trigger
GITHUB_TOKEN=<optional-github-token>  # enables merge-commit rerun detection
```

### 3. Install frontend dependencies

```bash
make install
```

### 4. Run the scraper (first-time)

```bash
make scrape
# or with a custom look-back window:
make scrape DAYS=90
```

A `tqdm` progress bar shows the 7 scraper steps in the terminal.  Data is
written to FalkorDB if reachable, otherwise to `~/.tekton-dashboard.db`.

### 5. Start the dashboard in dev mode

```bash
make dev
```

### 6. Build a distributable binary

```bash
make build
```

Output: `dashboard/src-tauri/target/release/bundle/`

## Crontab Setup

Add to crontab (`crontab -e`) to auto-scrape every morning at 06:00:

```cron
0 6 * * * /path/to/github-tekton-dashboard/scraper/run_scraper.sh >> /var/log/tekton-scraper.log 2>&1
```

## Data Cleanup

Remove all data for a specific pipeline (useful when switching pipelines or
resetting stale data):

```bash
# Preview what would be deleted
make cleanup PIPELINE_ID=<uuid> --dry-run   # (pass via env: PIPELINE_ID=... make cleanup)

# Delete one pipeline's data
make cleanup PIPELINE_ID=<tekton-pipeline-uuid>

# Full reset (wipe everything)
make cleanup-all
```

The cleanup script auto-detects the active backend (FalkorDB or SQLite) and
applies the correct deletion strategy.

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Overview** | KPI tiles + stage failure pie + rerun type pie + top-20 PR bars (clickable → PR detail) |
| **PRs** | PR list → click → run timeline scatter + duration histogram |
| **Errors** | Horizontal bar (% builds per error type) + detail grid cards |
| **Stages** | Stage failure pie + sortable table; click pie slice to filter |
| **Reruns** | Compute loss tile + dev productivity loss tile + per-PR table |
| **Settings** | Pipeline config reference + manual scraper trigger + last-scrape metadata |

### Stage failure attribution

The scraper calls the IBM Cloud CD `/logs` API to identify which pipeline stage
caused each failure.  Tekton **`finally`** tasks (e.g. `finish`) always run
regardless of whether earlier stages failed, so they always appear last in the
log list.  The scraper excludes `finally` tasks from "last = failing" logic and
instead finds the **last stage present** before the first **absent** stage in
the known pipeline order:

```
pr-start → pr-code-checks → pr-code-build → pr-deploy-checks
                                                      ↑ absent → pr-code-build is the failure
```

The `finish` stage is only attributed as the failing stage when all four
pipeline stages completed successfully.

## Time Window Filtering

Use the **7 days / 30 days / 90 days** buttons in the top nav.  
All charts and tables reactively re-query the active backend when the window changes.

## Development

```bash
# Python scraper linting
cd scraper && uv run ruff check

# Frontend only (no Tauri, uses Vite dev server)
cd dashboard && npm run dev

# Full Tauri dev (hot-reload frontend + compiled Rust backend)
make dev

# Rust type-check only (fast, no full compile)
make check-rust

# Python lint
make lint-py
```

## Graph / DB Schema

### FalkorDB nodes
`Pipeline`, `Run`, `PR`, `Stage`, `ErrorType`, `Developer`, `ScrapeMeta`

### FalkorDB edges
`HAS_RUN`, `BELONGS_TO_PR`, `AUTHORED_BY`, `HAS_STAGE`, `HAS_ERROR`, `IS_RERUN_OF`

### SQLite tables
`pipelines`, `runs`, `prs`, `run_stages`, `run_errors`, `reruns`, `scrape_meta`
