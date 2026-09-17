"""
analyze_stages — importable module wrapping analyze-stages-from-yaml.py logic.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


def _parse_yaml_simple(file_path: Path) -> list[dict[str, Any]]:
    """Minimal YAML parser: extract TaskRun name/status/reason without external deps."""
    task_runs: list[dict] = []
    in_taskrun = False
    current_name: Optional[str] = None
    current_status: Optional[str] = None
    current_reason: Optional[str] = None

    with open(file_path) as f:
        for line in f:
            line = line.rstrip()
            if line == "---":
                if current_name and current_status:
                    task_runs.append(
                        {"name": current_name, "status": current_status, "reason": current_reason}
                    )
                current_name = current_status = current_reason = None
                in_taskrun = False
                continue
            if "kind: TaskRun" in line:
                in_taskrun = True
                continue
            if not in_taskrun:
                continue
            if "  name: app-preview-pr" in line and "pipelinerun" in line:
                m = re.search(r"name: app-preview-pr-pipelinerun-(\S+)", line)
                if m:
                    stage = m.group(1)
                    current_name = stage.replace("app-preview-pr-", "") if not stage.startswith("pr-") else stage
            if "      status:" in line and current_name:
                m = re.search(r"status:\s*[\"']?(\w+)[\"']?", line)
                if m:
                    current_status = "succeeded" if m.group(1) in ("True", "true") else "failed"
            if "      reason:" in line and current_name:
                m = re.search(r"reason:\s*[\"']?(\w+)[\"']?", line)
                if m:
                    current_reason = m.group(1)

    if current_name and current_status:
        task_runs.append({"name": current_name, "status": current_status, "reason": current_reason})
    return task_runs


def _analyze_build(build_number: int, logs_base_dir: Path) -> Optional[dict[str, dict]]:
    yaml_path = logs_base_dir / str(build_number) / "logs-current" / "resultResources.yaml"
    if not yaml_path.exists():
        return None
    return {
        t["name"]: {"status": t["status"], "reason": t["reason"], "failed": t["status"] == "failed"}
        for t in _parse_yaml_simple(yaml_path)
    }


def analyze_stages(
    runs: list[dict],
    logs_base_dir: str = "",
) -> dict[str, Any]:
    """
    Parse resultResources.yaml for each run and aggregate stage failure stats.

    Args:
        runs:           Raw pipeline run dicts (from fetch_runs).
        logs_base_dir:  Path to per-build log directories.
                        Empty string or non-existent path → returns empty result.

    Returns:
        {
          'summary': {total_runs, runs_analyzed, stage_stats: {stage: {...}}},
          'run_details': [...]
        }
    """
    _empty = {"summary": {"total_runs": len(runs), "runs_analyzed": 0, "stage_stats": {}},
              "run_details": []}
    base = Path(logs_base_dir).resolve() if logs_base_dir else None
    if base is None or not base.exists():
        return _empty
    stage_stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "failed": 0, "succeeded": 0, "builds": []}
    )
    run_details: list[dict] = []

    for run in runs:
        build_number = run.get("build_number")
        status = run.get("status")
        stages = _analyze_build(build_number, base)
        if stages is None:
            continue
        detail: dict[str, Any] = {"build_number": build_number, "status": status, "stages": {}}
        for stage_name, stage_data in stages.items():
            stage_stats[stage_name]["total"] += 1
            if stage_data["failed"]:
                stage_stats[stage_name]["failed"] += 1
                stage_stats[stage_name]["builds"].append(build_number)
            else:
                stage_stats[stage_name]["succeeded"] += 1
            detail["stages"][stage_name] = stage_data
        run_details.append(detail)

    return {
        "summary": {
            "total_runs": len(runs),
            "runs_analyzed": len(run_details),
            "stage_stats": {
                k: {"total": v["total"], "failed": v["failed"],
                    "succeeded": v["succeeded"], "builds": v["builds"]}
                for k, v in stage_stats.items()
            },
        },
        "run_details": run_details,
    }
