.PHONY: scrape dev build clean

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

clean:
	rm -rf dashboard/dist dashboard/src-tauri/target scraper/logs/*.log
