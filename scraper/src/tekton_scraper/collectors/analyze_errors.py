"""
analyze_errors — importable module wrapping analyze-error-types.py logic.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ERROR_PATTERNS: dict[str, list[str]] = {
    "timeout": [
        r"\btimeout\b",
        r"exceeded.*time.*limit",
        r"timed out",
        r"deadline exceeded",
        r"execution timeout",
        r"Read timed out",
    ],
    "GS timeout": [r"\bwas not found in global search\b"],
    "UT test failure": [r"Task :data-product-api-common:test FAILED"],
    "FVT test failure": [
        r"Task :data-product-api-automation:DITest FAILED",
        r"Task :data-product-api-automation:DockerTest FAILED",
    ],
    "build_failure": [
        r"BUILD FAILED",
        r"compilation error",
        r"compile failed",
        r"build failed",
        r"build error:",
        r"gradle build failed",
        r"maven build failed",
        r"BUILD FAILURE",
    ],
    "lint_failure": [
        r"\bcheckstyle\b",
        r"lint error",
        r"style violation",
        r"formatting error",
        r"pmd violation",
    ],
    "dependency_issues": [
        r"artifact not found",
        r"dependency resolution failed",
        r"package not found",
        r"npm ERR!",
    ],
    "infrastructure": [
        r"connection refused",
        r"network error",
        r"unable to connect",
        r"docker error",
        r"kubernetes error",
        r"service unavailable",
        r"502 Bad Gateway",
        r"503 Service Unavailable",
    ],
    "merge_conflict": [
        r"merge conflict",
        r"\bCONFLICT\b",
        r"cannot merge",
        r"rebase failed",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {
    etype: [re.compile(p, re.IGNORECASE) for p in patterns]
    for etype, patterns in ERROR_PATTERNS.items()
}


def _analyze_log_file(log_path: Path) -> set[str]:
    detected: set[str] = set()
    try:
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        for etype, patterns in _COMPILED.items():
            if any(p.search(content) for p in patterns):
                detected.add(etype)
    except Exception:
        pass
    return detected


def _analyze_build_logs(build_dir: Path) -> set[str]:
    all_errors: set[str] = set()
    if build_dir.exists():
        for log_file in build_dir.rglob("*.log"):
            all_errors.update(_analyze_log_file(log_file))
    return all_errors


def analyze_errors(
    pr_analysis: list[dict],
    logs_base_dir: str = "",
) -> dict[str, Any]:
    """
    Scan downloaded log files for each failed run and categorize error types.

    Args:
        pr_analysis:   Output of analyze_runs().
        logs_base_dir: Path to the logs root directory.

    Returns:
        {
          'summary': {...},
          'error_types': {
            '<type>': {count, affected_prs, total_duration_seconds,
                       average_duration_seconds, builds}
          }
        }
    """
    base = Path(logs_base_dir).resolve() if logs_base_dir else None
    _empty = {"summary": {"total_failed_builds": 0, "builds_with_logs": 0,
                           "builds_without_logs": 0, "uncategorized_failures": 0},
              "error_types": {}}
    if base is None or not base.exists():
        return _empty

    error_stats: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "prs": set(), "total_duration": 0.0, "builds": []}
    )
    total_analyzed = 0
    total_with_logs = 0
    uncategorized = 0

    for pr in pr_analysis:
        pr_number = pr["pr_number"]
        for run in pr.get("runs", []):
            if run.get("status") != "failed":
                continue
            total_analyzed += 1
            build_number = run.get("build_number")
            duration = run.get("duration_seconds", 0.0)

            detected: set[str] = set()
            found_logs = False

            for service_dir in base.iterdir():
                if not service_dir.is_dir():
                    continue
                build_path = service_dir / "pr" / str(build_number)
                if not build_path.exists():
                    continue
                logs_dir = build_path / "logs-current"
                if not logs_dir.exists():
                    for item in build_path.iterdir():
                        if item.is_dir() and item.name.startswith("logs-"):
                            logs_dir = item
                            break
                if logs_dir and logs_dir.exists():
                    found_logs = True
                    detected = _analyze_build_logs(logs_dir)
                    break

            if found_logs:
                total_with_logs += 1
                if detected:
                    for etype in detected:
                        error_stats[etype]["count"] += 1
                        error_stats[etype]["prs"].add(pr_number)
                        error_stats[etype]["total_duration"] += duration
                        error_stats[etype]["builds"].append(
                            {"pr": pr_number, "build": build_number, "duration": duration}
                        )
                else:
                    uncategorized += 1
                    error_stats["uncategorized"]["count"] += 1
                    error_stats["uncategorized"]["prs"].add(pr_number)
                    error_stats["uncategorized"]["total_duration"] += duration
                    error_stats["uncategorized"]["builds"].append(
                        {"pr": pr_number, "build": build_number, "duration": duration}
                    )

    return {
        "summary": {
            "total_failed_builds": total_analyzed,
            "builds_with_logs": total_with_logs,
            "builds_without_logs": total_analyzed - total_with_logs,
            "uncategorized_failures": uncategorized,
        },
        "error_types": {
            etype: {
                "count": stats["count"],
                "affected_prs": sorted(stats["prs"]),
                "total_duration_seconds": stats["total_duration"],
                "average_duration_seconds": (
                    stats["total_duration"] / stats["count"] if stats["count"] else 0.0
                ),
                "builds": stats["builds"],
            }
            for etype, stats in error_stats.items()
        },
    }
