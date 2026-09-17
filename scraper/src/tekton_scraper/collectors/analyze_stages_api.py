"""
analyze_stages_from_api — fetch stage failure data directly from the IBM Cloud
CD pipeline /logs endpoint, without needing downloaded log archives.

For each failed run the /logs API returns a list of log entries whose names
contain the stage (TaskRun) name:
    app-preview-pr-pipelinerun-<stage>-pod/<step>

IMPORTANT — Tekton "finally" tasks:
DevSecOps pipelines include a "finish" task declared as a Tekton `finally`
block.  It always runs regardless of whether earlier stages succeeded or
failed.  This means the finish stage log entries ALWAYS appear last in the
log list — even for runs where the real failure was in pr-code-build.

Naive algorithm ("last stage in log list = failing stage") therefore
mis-attributes almost every failure to the finish stage.

Correct algorithm:
1. Collect the ordered list of PIPELINE stages seen in the logs, excluding
   the known finally-tasks (finish variants).
2. Compare against the known ordered stage sequence for this pipeline.
3. The LAST present non-finally stage is the true failing stage, because
   all subsequent pipeline stages were skipped (never logged) due to the
   failure.
4. Finally-tasks themselves can genuinely fail — if ALL expected pipeline
   stages are present AND finish appears, then finish is the failing stage.

Requests are issued concurrently via ThreadPoolExecutor to avoid the
sequential HTTP round-trip bottleneck.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import json
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tekton_scraper.collectors.config import PipelineConfig

logger = logging.getLogger(__name__)

# Regex to extract the stage name from a log entry name like:
#   app-preview-pr-pipelinerun-pr-code-build-pod/start
# captures everything between the last "pipelinerun-" and the "-pod/" suffix.
_STAGE_RE = re.compile(r"pipelinerun-(.+?)-pod/")

# Maximum parallel HTTP requests to the IBM Cloud API.
_MAX_WORKERS = 10

# Stage names that are Tekton "finally" tasks — they always run regardless
# of whether the pipeline succeeded or failed, so they should never be
# counted as the cause of failure unless ALL regular pipeline stages ran.
# These are matched as SUFFIXES so that pipeline-prefixed variants
# (e.g. "app-preview-pr-finish") are also recognised.
_FINALLY_STAGE_SUFFIXES = (
    "finish",
    "pr-finish",
)

# Known ordered pipeline stage sequence (excluding finally tasks).
# Stages are listed in execution order. When a stage fails, all subsequent
# stages are absent from the log list.
# This list is used as a fallback when the pipeline's stage order cannot be
# inferred from a single run's logs.
_DEFAULT_STAGE_ORDER = [
    "pr-start",
    "pr-code-checks",
    "pr-code-build",
    "pr-deploy-checks",
]


def _is_finally_stage(stage_name: str) -> bool:
    """Return True if *stage_name* looks like a Tekton finally task."""
    lower = stage_name.lower()
    return any(lower == s or lower.endswith("-" + s) for s in _FINALLY_STAGE_SUFFIXES)


def _fetch_run_log_entries(
    run_id: str,
    config: PipelineConfig,
    token: str,
) -> list[str]:
    """Return ordered list of unique stage names for a single run via the /logs API."""
    url = (
        f"https://api.{config.region}.devops.cloud.ibm.com"
        f"/pipeline/v2/tekton_pipelines/{config.pipeline_id}"
        f"/pipeline_runs/{run_id}/logs"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        logger.debug("HTTP %s fetching logs for run %s", exc.code, run_id)
        return []
    except Exception as exc:
        logger.debug("Error fetching logs for run %s: %s", run_id, exc)
        return []

    stages: list[str] = []
    for entry in data.get("logs", []):
        m = _STAGE_RE.search(entry.get("name", ""))
        if m:
            stage = m.group(1)
            if stage not in stages:
                stages.append(stage)
    return stages


def _identify_failing_stage(
    stages: list[str],
    stage_order: list[str],
) -> str:
    """
    Given the ordered list of stage names that appeared in the logs and the
    known pipeline stage order (excluding finally tasks), return the name of
    the stage that actually caused the failure.

    Logic
    -----
    1. Split *stages* into pipeline stages and finally stages.
    2. Walk *stage_order* and find the last pipeline stage that IS present in
       the run's logs — all subsequent ordered stages were skipped because
       this stage failed.
    3. If ALL ordered stages are present → the failure is in the finally task
       (return the last finally-stage seen in *stages*).
    4. If no ordered stage is present at all → fall back to the raw last entry.
    """
    pipeline_stages_seen = [s for s in stages if not _is_finally_stage(s)]
    finally_stages_seen  = [s for s in stages if _is_finally_stage(s)]

    if not pipeline_stages_seen:
        # Only finally stages (or nothing) — return last stage as-is
        return stages[-1] if stages else "unknown"

    # Build an ordered list of pipeline stages that appeared
    # using stage_order as the authoritative sequence
    ordered_seen = [s for s in stage_order if s in pipeline_stages_seen]
    # Also include any stages that appear in the run but not in stage_order
    extra = [s for s in pipeline_stages_seen if s not in stage_order]

    # Check if ALL known ordered stages are present
    all_ordered_present = all(s in pipeline_stages_seen for s in stage_order)

    if all_ordered_present:
        # Every pipeline stage ran → the failure is in the finally task
        if finally_stages_seen:
            return finally_stages_seen[-1]
        # No finally stage seen at all — use last pipeline stage
        return ordered_seen[-1] if ordered_seen else (extra[-1] if extra else stages[-1])

    # Find the last PRESENT stage in the known order — that's the one that failed
    last_present = None
    for s in stage_order:
        if s in pipeline_stages_seen:
            last_present = s
        else:
            # This stage is ABSENT — the previous stage (last_present) failed
            break

    if last_present:
        return last_present

    # Fallback: use the last non-finally stage seen
    return pipeline_stages_seen[-1]


def analyze_stages_from_api(
    runs: list[dict],
    config: PipelineConfig,
    token: str,
    limit: int = 200,
    max_workers: int = _MAX_WORKERS,
    stage_order: list[str] | None = None,
) -> dict[str, Any]:
    """
    Derive stage failure statistics by querying the IBM Cloud CD /logs API
    for each failed run, using concurrent HTTP requests.

    The true failing stage is identified by comparing the stages that
    *appeared* in the logs against the known pipeline stage order.  Finally
    tasks (e.g. "finish") are excluded from this comparison unless every
    regular pipeline stage completed successfully.

    Args:
        runs:        Raw pipeline run dicts from fetch_runs().
        config:      PipelineConfig with region/pipeline_id.
        token:       Valid IAM Bearer token.
        limit:       Maximum number of failed runs to query (avoids rate-limiting).
        max_workers: Thread-pool size for concurrent API calls.
        stage_order: Ordered list of pipeline stages (non-finally) to use for
                     failure attribution.  Defaults to _DEFAULT_STAGE_ORDER.

    Returns same shape as analyze_stages():
        {
          'summary': {total_runs, runs_analyzed, stage_stats: {stage: {...}}},
          'run_details': [...]
        }
    """
    if stage_order is None:
        stage_order = _DEFAULT_STAGE_ORDER

    # Collect the failed runs to process (up to limit)
    failed_runs: list[dict] = []
    for run in runs:
        if run.get("status", "") != "failed":
            continue
        run_id = run.get("id") or run.get("run_id", "")
        if not run_id:
            continue
        failed_runs.append(run)
        if len(failed_runs) >= limit:
            logger.info("Stage API query limit (%d) reached, capping.", limit)
            break

    logger.info(
        "Stage API analysis: fetching logs for %d failed runs (max_workers=%d)…",
        len(failed_runs),
        max_workers,
    )

    # Fire all requests concurrently; results keyed by run_id
    raw_results: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_run = {
            pool.submit(
                _fetch_run_log_entries,
                run.get("id") or run.get("run_id", ""),
                config,
                token,
            ): run
            for run in failed_runs
        }
        for future in as_completed(future_to_run):
            run = future_to_run[future]
            run_id = run.get("id") or run.get("run_id", "")
            try:
                stages = future.result()
            except Exception as exc:
                logger.debug("Unexpected error for run %s: %s", run_id, exc)
                stages = []
            raw_results[run_id] = stages

    # Aggregate stats in original run order
    stage_stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "failed": 0, "succeeded": 0, "builds": []}
    )
    run_details: list[dict] = []

    for run in failed_runs:
        run_id = run.get("id") or run.get("run_id", "")
        build_number = run.get("build_number")
        stages = raw_results.get(run_id, [])
        if not stages:
            continue

        # Identify the true failing stage (correctly handles finally tasks)
        failing_stage = _identify_failing_stage(stages, stage_order)
        detail_stages: dict[str, dict] = {}

        for stage_name in stages:
            failed = stage_name == failing_stage
            stage_stats[stage_name]["total"] += 1
            if failed:
                stage_stats[stage_name]["failed"] += 1
                stage_stats[stage_name]["builds"].append(build_number)
            else:
                stage_stats[stage_name]["succeeded"] += 1
            detail_stages[stage_name] = {
                "status": "failed" if failed else "succeeded",
                "reason": None,
                "failed": failed,
            }

        run_details.append({
            "build_number": build_number,
            "status": run.get("status", ""),
            "stages": detail_stages,
        })

    logger.info(
        "Stage API analysis: queried %d failed runs, got data for %d",
        len(failed_runs),
        len(run_details),
    )
    return {
        "summary": {
            "total_runs": len(runs),
            "runs_analyzed": len(run_details),
            "stage_stats": {
                k: {
                    "total": v["total"],
                    "failed": v["failed"],
                    "succeeded": v["succeeded"],
                    "builds": v["builds"],
                }
                for k, v in stage_stats.items()
            },
        },
        "run_details": run_details,
    }
