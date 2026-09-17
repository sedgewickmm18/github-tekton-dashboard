"""
analyze_runs — importable module wrapping analyze-pr-runs.py logic.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional


def _parse_pr_number(event_params_blob: str) -> Optional[int]:
    try:
        d = json.loads(event_params_blob)
        return d.get("number") or d.get("pull_request", {}).get("number")
    except Exception:
        return None


def _calculate_duration(created_at: str, updated_at: str) -> float:
    try:
        c = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        u = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return (u - c).total_seconds()
    except Exception:
        return 0.0


def analyze_runs(runs: list[dict]) -> list[dict[str, Any]]:
    """
    Group raw pipeline runs by PR number and compute per-PR statistics.

    Returns a list of PR analysis dicts, sorted by total_runs descending.
    Each dict contains:
        pr_number, pr_title, pr_author, pr_url,
        total_runs, failed, succeeded, cancelled, error,
        total_duration_seconds, runs (list of raw run dicts)
    """
    pr_groups: dict[int, list[dict]] = defaultdict(list)

    for run in runs:
        pr_num = _parse_pr_number(run.get("event_params_blob", ""))
        if pr_num is not None:
            pr_groups[pr_num].append(run)

    result = []
    for pr_number, pr_runs in pr_groups.items():
        pr_runs.sort(key=lambda x: x.get("created_at", ""))

        status_counts: dict[str, int] = defaultdict(int)
        for r in pr_runs:
            status_counts[r.get("status", "unknown")] += 1

        total_duration = sum(
            _calculate_duration(r.get("created_at", ""), r.get("updated_at", ""))
            for r in pr_runs
        )

        first = pr_runs[0]
        try:
            ep = json.loads(first.get("event_params_blob", "{}"))
            pr_obj = ep.get("pull_request", {})
            pr_title = pr_obj.get("title", "N/A")
            pr_author = pr_obj.get("user", {}).get("login", "N/A")
            pr_url = pr_obj.get("html_url", "N/A")
            pr_created_at = pr_obj.get("created_at", "")
        except Exception:
            pr_title = pr_author = pr_url = "N/A"
            pr_created_at = ""

        result.append(
            {
                "pr_number": pr_number,
                "pr_title": pr_title,
                "pr_author": pr_author,
                "pr_url": pr_url,
                "pr_created_at": pr_created_at,
                "total_runs": len(pr_runs),
                "failed": status_counts["failed"],
                "succeeded": status_counts["succeeded"],
                "cancelled": status_counts["cancelled"],
                "error": status_counts["error"],
                "total_duration_seconds": total_duration,
                "runs": pr_runs,
            }
        )

    result.sort(key=lambda x: x["total_runs"], reverse=True)
    return result
