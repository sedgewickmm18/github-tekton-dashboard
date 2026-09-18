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

web-spa/          Static SPA for GitHub Pages (no Tauri dependency)
  src/            Svelte frontend + sql.js (WebAssembly SQLite loader)
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
REPO_GITHUB_TOKEN=<optional-github-token>   # (or GITHUB_TOKEN / GH_TOKEN) enables merge-commit rerun detection
PIPELINE_URL=<ibm-cloud-console-url>   # optional — quick link in Settings tab
GITHUB_REPO_URL=<github-repo-url>      # optional — quick link in Settings tab
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
| **Settings** | Pipeline config reference + manual scraper trigger + last-scrape metadata *(desktop only)* |

## GitHub Pages Web Dashboard

In addition to the Tauri desktop app, a fully static Single Page Application (SPA) variant is provided in `web-spa/` and can be hosted directly on **GitHub Pages**.

### How it works
1. A GitHub Actions workflow (`.github/workflows/pages.yml`) runs on a schedule (daily at 06:00 UTC) or on push / manual trigger.
2. The workflow executes the Python scraper in SQLite mode, outputting a fresh `dashboard.db` to `web-spa/public/dashboard.db`.
3. The Svelte web app builds using Vite, bundling `sql.js` (WebAssembly SQLite engine).
4. When users visit the GitHub Pages URL, the browser downloads `dashboard.db` and queries it client-side with zero backend server required.
5. Note: The **Settings** tab (and manual scraper trigger) is omitted in the static web version; scraping is handled automatically by GitHub Actions.

### Setup GitHub Pages deployment

1. In your GitHub repository, go to **Settings > Secrets and variables > Actions**.
2. Add the following repository secrets (matching your `pipeline.env` configuration):
   - `IBM_CLOUD_API_KEY`: Your IBM Cloud API key *(Required)*
   - `PIPELINE_ID`: Tekton pipeline UUID *(Required)*
   - `REGION`: IBM Cloud region (e.g., `us-south`) *(Optional, defaults to us-south)*
   - `TRIGGER_NAME`: Tekton trigger name *(Optional, defaults to pr-trigger)*
   - `REPO_GITHUB_TOKEN`: GitHub Personal Access Token for commit comparisons *(Optional; note that GitHub disallows creating custom secrets starting with `GITHUB_`, so use `REPO_GITHUB_TOKEN` or `GH_TOKEN`)*
   - `PIPELINE_URL`: Direct link to IBM Cloud console pipeline *(Optional)*
   - `GITHUB_REPO_URL`: URL to your GitHub repository *(Optional)*
3. Go to **Settings > Pages**:
   - Under **Build and deployment > Source**, select **GitHub Actions**.
4. Trigger the workflow manually from the **Actions** tab or push a commit to `main`.
5. Your dashboard will be live at `https://<username>.github.io/<repo-name>/`.

### Local Web SPA development

```bash
# Install dependencies
make web-spa-install

# Copy an existing SQLite database for local testing
cp ~/.tekton-dashboard.db web-spa/public/dashboard.db

# Start Vite dev server
make web-spa-dev

# Build static bundle for production
make web-spa-build

# Preview built production bundle
make web-spa-preview
```

### Local GitHub Actions Workflow Simulation & Test Procedure

You can test the entire GitHub Actions build and deployment pipeline locally using [`scripts/test-gha-workflow.sh`](scripts/test-gha-workflow.sh:1) or the Makefile targets.

The test procedure executes:
1. **Runner checks:** Asserts required tools (`uv`, `python3`, `node`, `npm`) are installed.
2. **Scraping step:** Runs the scraper in SQLite mode writing to `web-spa/public/dashboard.db` (auto-detects credentials in `pipeline.env` or seeds a synthetic database).
3. **Build step:** Installs dependencies and executes `npm run build` with Vite inside `web-spa/`.
4. **Artifact validation:** Asserts required production artifacts are present and non-empty in `web-spa/dist/` (`index.html`, `dashboard.db`, `sql-wasm.wasm`).
5. **Optional Preview:** Automatically runs Vite preview on localhost.

```bash
# Run full simulation (uses live credentials if available, otherwise synthetic mock data)
make test-gha

# Run simulation explicitly using synthetic mock test fixtures
make test-gha-mock

# Run simulation and launch preview server in browser
make test-gha-preview

# Or run the script directly with options
./scripts/test-gha-workflow.sh --help
./scripts/test-gha-workflow.sh --mock --preview
```

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
