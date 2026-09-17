"""
calc_open_times — importable module wrapping calculate-pr-open-time.py logic.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def calc_open_times(pr_analysis: list[dict]) -> list[dict[str, Any]]:
    """
    For each PR compute time between PR creation and the last pipeline run.

    Args:
        pr_analysis: Output of analyze_runs().

    Returns:
        List of dicts sorted by open_duration_seconds descending. Each dict:
            pr_number, pr_title, pr_author, pr_url,
            pr_created_at, last_run_at,
            open_duration_seconds, total_runs, failed, succeeded
    """
    result: list[dict] = []

    for pr in pr_analysis:
        runs = pr.get("runs", [])
        if not runs:
            continue

        # Extract PR created_at from first run's event params
        pr_created: Optional[datetime] = None
        try:
            ep = json.loads(runs[0].get("event_params_blob", "{}"))
            ts = ep.get("pull_request", {}).get("created_at")
            if ts:
                pr_created = _parse_ts(ts)
        except Exception:
            pass

        # Last run timestamp
        run_times = []
        for r in runs:
            try:
                run_times.append(_parse_ts(r["created_at"]))
            except Exception:
                pass

        if not pr_created or not run_times:
            continue

        last_run = max(run_times)
        duration = (last_run - pr_created).total_seconds()

        result.append(
            {
                "pr_number": pr["pr_number"],
                "pr_title": pr["pr_title"],
                "pr_author": pr["pr_author"],
                "pr_url": pr["pr_url"],
                "pr_created_at": pr_created.isoformat(),
                "last_run_at": last_run.isoformat(),
                "open_duration_seconds": duration,
                "total_runs": pr["total_runs"],
                "failed": pr["failed"],
                "succeeded": pr["succeeded"],
            }
        )

    result.sort(key=lambda x: x["open_duration_seconds"], reverse=True)
    return result
