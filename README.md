# Tekton Pipeline Dashboard

A reactive desktop dashboard for IBM Cloud Tekton pipeline analytics.  
Python scraper → FalkorDB graph store → Tauri + Svelte frontend.

## Architecture

```
scraper/          Python uv project — fetches IBM Cloud Tekton data, writes to FalkorDB
  collectors/     Pure function modules (no CLI boilerplate)
  db/             FalkorDB schema, migration, writer
  main.py         Orchestrator entry point
  run_scraper.sh  Cron-friendly shell wrapper

dashboard/        Tauri v2 desktop app
  src/            Svelte frontend (App, stores, pages)
  src-tauri/      Rust backend (FalkorDB Cypher commands via Redis protocol)
```

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| FalkorDB | latest | `docker run -p 6379:6379 falkordb/falkordb` |
| Python | 3.11+ | [python.org](https://python.org) |
| uv | latest | `curl -Ls https://astral.sh/uv/install.sh \| sh` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) |
| Rust + Cargo | 1.77+ | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Tauri CLI | 2.x | installed via `npm install` in `dashboard/` |

## Quick Start

### 1. Start FalkorDB

```bash
docker run -d --name falkordb -p 6379:6379 falkordb/falkordb
```

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

### 3. Run the scraper (first-time)

```bash
make scrape
# or with custom days:
make scrape DAYS=14
```

### 4. Start the dashboard in dev mode

```bash
make dev
```

### 5. Build a distributable binary

```bash
make build
```

Outputs: `dashboard/src-tauri/target/release/bundle/`

## Crontab Setup

Add to crontab (`crontab -e`) to auto-scrape every morning at 06:00:

```cron
0 6 * * * /path/to/github-tekton-dashboard/scraper/run_scraper.sh >> /var/log/tekton-scraper.log 2>&1
```

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Overview** | KPI cards + stage pie + error doughnut + top-20 PR bar chart |
| **PRs** | PR list → click → run timeline scatter + duration histogram |
| **Errors** | Horizontal bar (% builds per error type) + detail grid cards |
| **Stages** | Stage failure pie + sortable table; click pie slice to filter |
| **Reruns** | Compute loss tile + dev productivity loss tile + per-PR table |
| **Settings** | Pipeline config reference + manual scraper trigger + last-scrape metadata |

## Time Window Filtering

Use the **7 days / 30 days / 90 days** buttons in the top nav.  
All charts and tables reactively re-query FalkorDB when the window changes.

## Development

```bash
# Python scraper linting
cd scraper && uv run ruff check

# Frontend only (no Tauri)
cd dashboard && npm run dev

# Full Tauri dev (hot-reload)
cd dashboard && npm run tauri dev

# Rust type-check only
cd dashboard/src-tauri && cargo check
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FALKORDB_HOST` | `localhost` | FalkorDB host |
| `FALKORDB_PORT` | `6379` | FalkorDB port |
| `FALKORDB_GRAPH` | `tekton-dashboard` | Graph name |

## Graph Schema

Nodes: `Pipeline`, `Run`, `PR`, `Commit`, `Stage`, `ErrorType`, `Developer`, `ScrapeMeta`  
Edges: `HAS_RUN`, `BELONGS_TO_PR`, `AUTHORED_BY`, `HAS_STAGE`, `HAS_ERROR`, `IS_RERUN_OF`
