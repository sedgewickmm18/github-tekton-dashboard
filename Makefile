.PHONY: scrape dev build clean web-spa-dev web-spa-build web-spa-preview web-spa-install test-gha test-web-spa test-gha-mock test-gha-preview

DAYS ?= 90

## Run the scraper (fetches last DAYS days of pipeline data)
scrape:
	cd scraper && SCRAPER_DAYS=$(DAYS) bash run_scraper.sh

## Start Tauri + Svelte in development mode (hot-reload)
dev:
	cd dashboard && npm run tauri dev

## Build a production Tauri bundle (AppImage / dmg / msi)
build:
	cd dashboard && npm run tauri build

## Install all frontend dependencies
install:
	cd dashboard && npm install

## Type-check the Rust backend without building
check-rust:
	cd dashboard/src-tauri && cargo check

## Lint the Python scraper
lint-py:
	cd scraper && uv run ruff check

## Remove data for a specific pipeline ID (FalkorDB or SQLite)
## Usage: make cleanup PIPELINE_ID=<id>   or   make cleanup-all
cleanup:
	cd scraper && uv run python cleanup_pipeline.py --pipeline-id $(PIPELINE_ID)

cleanup-all:
	cd scraper && uv run python cleanup_pipeline.py --all

## Install dependencies for static web SPA
web-spa-install:
	cd web-spa && npm install

## Run static web SPA in development mode
web-spa-dev:
	cd web-spa && npm run dev

## Build static web SPA for GitHub Pages
web-spa-build:
	cd web-spa && npm run build

## Preview static web SPA production build
web-spa-preview:
	cd web-spa && npm run preview

## Test GitHub Actions workflow simulation (scrapes or uses mock, builds, validates dist)
test-gha:
	./scripts/test-gha-workflow.sh

test-web-spa: test-gha

## Test GitHub Actions workflow using synthetic mock data
test-gha-mock:
	./scripts/test-gha-workflow.sh --mock

## Test GitHub Actions workflow and open preview server
test-gha-preview:
	./scripts/test-gha-workflow.sh --preview

clean:
	rm -rf dashboard/dist dashboard/src-tauri/target web-spa/dist scraper/logs/*.log
