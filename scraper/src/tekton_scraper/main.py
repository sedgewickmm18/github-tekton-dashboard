"""
Scraper orchestrator — fetches pipeline data and writes to FalkorDB or SQLite.

Usage:
    uv run python -m tekton_scraper.main [--days N] [--env pipeline.env]
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from tqdm import tqdm

from tekton_scraper.collectors.config import PipelineConfig
from tekton_scraper.collectors.fetch_runs import fetch_runs
from tekton_scraper.collectors.analyze_runs import analyze_runs
from tekton_scraper.collectors.analyze_reruns import analyze_reruns
from tekton_scraper.collectors.analyze_errors import analyze_errors
from tekton_scraper.collectors.analyze_stages import analyze_stages
from tekton_scraper.collectors.analyze_stages_api import analyze_stages_from_api
from tekton_scraper.db.client import active_backend, get_graph
from tekton_scraper.db.migrate import migrate
from tekton_scraper.db.writer import (
    upsert_pipeline,
    upsert_prs,
    upsert_runs,
    upsert_stages,
    upsert_errors,
    upsert_reruns,
)

logger = logging.getLogger("scraper")

LOG_DIR = Path(__file__).parent / "logs"


def _setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "scraper.log", maxBytes=5 * 1024 * 1024, backupCount=3
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.root.addHandler(handler)
    logging.root.addHandler(logging.StreamHandler(sys.stdout))
    logging.root.setLevel(level)


# Steps shown in the terminal progress bar
_STEPS = [
    "schema migration",
    "fetch runs",
    "upsert pipeline/PRs/runs",
    "rerun analysis",
    "error analysis",
    "stage analysis",
    "save metadata",
]


def run_pipeline(config: PipelineConfig, days: int = 30) -> dict:
    """
    Full scrape-and-store pipeline.

    Args:
        config: PipelineConfig loaded from pipeline.env.
        days:   Number of days to look back.

    Returns:
        Summary dict with counts.
    """
    logger.info("Starting scrape: last %d days", days)

    bar = tqdm(
        total=len(_STEPS),
        desc="Scraping",
        unit="step",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}",
        file=sys.stderr,
        dynamic_ncols=True,
    )

    def _step(name: str) -> None:
        bar.set_postfix_str(name)
        bar.update(1)

    # Ensure schema indexes exist
    bar.set_postfix_str("schema migration")
    migrate()
    _step("fetch runs")

    # 1. Fetch raw runs (token is returned so we can reuse it for stage analysis)
    logger.info("Fetching pipeline runs…")
    raw_runs, iam_token = fetch_runs(config, days=days)
    logger.info("Fetched %d runs", len(raw_runs))
    _step("upsert pipeline/PRs/runs")

    # 2. Ensure pipeline node exists
    upsert_pipeline(
        pipeline_id=config.pipeline_id,
        name=config.pipeline_id,
        region=config.region,
        trigger_name=config.trigger_name,
    )

    # 3. Analyze & upsert runs
    logger.info("Analyzing runs by PR…")
    pr_analysis = analyze_runs(raw_runs)

    # Flatten runs for writer — attach pr_number + author
    import json as _json
    from datetime import datetime
    flat_runs = []
    for pr in pr_analysis:
        for run in pr["runs"]:
            created = run.get("created_at", "")
            updated = run.get("updated_at", "")
            try:
                dur = (
                    datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    - datetime.fromisoformat(created.replace("Z", "+00:00"))
                ).total_seconds()
            except Exception:
                dur = 0.0
            sha = None
            try:
                ep = _json.loads(run.get("event_params_blob", "{}"))
                sha = ep.get("pull_request", {}).get("head", {}).get("sha")
            except Exception:
                pass
            flat_runs.append(
                {
                    "run_id": run.get("id") or run.get("run_id", ""),
                    "build_number": run.get("build_number"),
                    "status": run.get("status"),
                    "created_at": created,
                    "updated_at": updated,
                    "duration_seconds": dur,
                    "pr_number": pr["pr_number"],
                    "pr_author": pr["pr_author"],
                    "commit_sha": sha,
                }
            )

    # Upsert PRs
    pr_nodes = [
        {
            "pr_number": pr["pr_number"],
            "title": pr["pr_title"],
            "author": pr["pr_author"],
            "url": pr["pr_url"],
            "created_at": pr.get("pr_created_at", ""),
        }
        for pr in pr_analysis
    ]
    logger.info("Upserting %d PRs…", len(pr_nodes))
    upsert_prs(pr_nodes)
    logger.info("Upserting %d runs…", len(flat_runs))
    upsert_runs(config.pipeline_id, flat_runs)
    _step("rerun analysis")

    # 4. Rerun analysis
    logger.info("Analyzing reruns…")
    rerun_data = analyze_reruns(raw_runs, github_token=config.github_token)
    rerun_pairs = []
    for pr_num, stats in rerun_data["pr_stats"].items():
        for detail in stats["rerun_details"]:
            if detail.get("run_id") and detail.get("prev_run_id"):
                rerun_pairs.append(
                    {
                        "run_id": detail["run_id"],
                        "prev_run_id": detail["prev_run_id"],
                        "rerun_type": detail["rerun_type"],
                        # Wasted seconds stored on the edge so the query doesn't
                        # need to join against the Run node (prev run may be
                        # outside the stored time window).
                        "wasted_seconds": detail.get("duration", 0.0),
                    }
                )
    if rerun_pairs:
        upsert_reruns(rerun_pairs)
    _step("error analysis")

    # 5. Error type analysis (requires local logs)
    logger.info("Analyzing error types from logs…")
    error_data = analyze_errors(pr_analysis, logs_base_dir=config.logs_base_dir)
    run_error_items = []
    for etype, stats in error_data["error_types"].items():
        for build in stats["builds"]:
            # We need run_id; resolve by build_number
            for pr in pr_analysis:
                for run in pr["runs"]:
                    if run.get("build_number") == build["build"]:
                        run_id = run.get("id") or run.get("run_id", "")
                        if run_id:
                            run_error_items.append({"run_id": run_id, "error_type": etype})
    if run_error_items:
        upsert_errors(run_error_items)
    _step("stage analysis")

    # 6. Stage analysis
    # Primary: query the IBM Cloud /logs API (no local files needed).
    # Secondary: YAML file parse (adds richer detail when logs are downloaded).
    logger.info("Analyzing stage failures via IBM Cloud logs API…")
    stage_data = analyze_stages_from_api(raw_runs, config, iam_token)

    # If local logs exist, merge in the more-detailed YAML results
    if config.logs_base_dir:
        logger.info("Also checking local YAML logs for stage detail…")
        yaml_stage_data = analyze_stages(raw_runs, logs_base_dir=config.logs_base_dir)
        if yaml_stage_data["run_details"]:
            logger.info(
                "Merging %d YAML-based stage records",
                len(yaml_stage_data["run_details"]),
            )
            stage_data = yaml_stage_data  # prefer richer YAML data when available

    run_stage_items = []
    # Build a run_id lookup by build_number
    run_id_by_build: dict[int, str] = {}
    for pr in pr_analysis:
        for run in pr["runs"]:
            bn = run.get("build_number")
            rid = run.get("id") or run.get("run_id", "")
            if bn and rid:
                run_id_by_build[bn] = rid
    for detail in stage_data["run_details"]:
        bn = detail["build_number"]
        run_id = run_id_by_build.get(bn)
        if not run_id:
            continue
        for stage_name, stage_info in detail["stages"].items():
            run_stage_items.append(
                {
                    "run_id": run_id,
                    "stage_name": stage_name,
                    "status": stage_info["status"],
                    "reason": stage_info.get("reason"),
                }
            )
    if run_stage_items:
        upsert_stages(run_stage_items)
    _step("save metadata")

    # 7. Record scrape metadata
    import datetime
    bar.set_postfix_str("done")
    bar.close()
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    if active_backend() == "falkordb":
        get_graph().query(
            """
            MERGE (m:ScrapeMeta {key: 'latest'})
            SET m.last_scraped_at = $ts, m.run_count = $run_count, m.days = $days
            """,
            {"ts": ts, "run_count": len(flat_runs), "days": days},
        )
    else:
        from tekton_scraper.db.sqlite_backend import upsert_scrape_meta
        upsert_scrape_meta(
            ts, len(flat_runs), days,
            pipeline_url=config.pipeline_url,
            github_repo_url=config.github_repo_url,
        )

    summary = {
        "runs_fetched": len(raw_runs),
        "prs_analyzed": len(pr_analysis),
        "reruns_detected": sum(s["rerun_count"] for s in rerun_data["pr_stats"].values()),
        "error_types_found": len(error_data["error_types"]),
        "stages_analyzed": len(run_stage_items),
    }
    logger.info("Scrape complete: %s", summary)
    return summary


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Tekton Dashboard scraper")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument(
        "--env",
        default="pipeline.env",
        help="Path to pipeline.env file (default: pipeline.env)",
    )
    args = parser.parse_args()

    config = PipelineConfig.from_env_file(args.env)
    if not config.is_valid():
        logger.error("Missing required config in %s", args.env)
        sys.exit(1)

    run_pipeline(config, days=args.days)


if __name__ == "__main__":
    main()
