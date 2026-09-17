"""
analyze_reruns — importable module wrapping analyze-pr-reruns.py logic.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional


def _parse_pr_number(blob: str) -> Optional[int]:
    try:
        d = json.loads(blob)
        return d.get("number") or d["pull_request"]["number"]
    except Exception:
        return None


def _extract_head_sha(blob: str) -> Optional[str]:
    try:
        d = json.loads(blob)
        return d["pull_request"]["head"]["sha"]
    except Exception:
        return None


def _calculate_duration(created_at: str, updated_at: str) -> float:
    try:
        c = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        u = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        return (u - c).total_seconds()
    except Exception:
        return 0.0


def _extract_repo(runs: list[dict]) -> Optional[str]:
    for run in runs[:10]:
        try:
            d = json.loads(run.get("event_params_blob", "{}"))
            name = d.get("pull_request", {}).get("base", {}).get("repo", {}).get("full_name", "")
            if name:
                return name
        except Exception:
            pass
    return None


def _fetch_pr_commits(
    repo: str, pr_number: int, token: str, cache: dict
) -> list[dict]:
    key = f"{repo}:{pr_number}"
    if key in cache:
        return cache[key]
    url = f"https://github.ibm.com/api/v3/repos/{repo}/pulls/{pr_number}/commits"
    try:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            commits = json.loads(resp.read().decode())
            cache[key] = commits
            return commits
    except Exception:
        cache[key] = []
        return []


_MERGE_PATTERNS = [
    re.compile(r"^Merge branch ['\"]?main['\"]?", re.IGNORECASE),
    re.compile(r"^Merge branch ['\"]?master['\"]?", re.IGNORECASE),
    re.compile(r"^Merge remote-tracking branch", re.IGNORECASE),
]


def analyze_reruns(
    runs: list[dict],
    github_token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Detect pipeline reruns (same SHA or merge commits) and compute productivity loss.

    Returns:
        {
          'pr_stats': {pr_number: {...}},
          'total_prs': int,
          'total_runs': int,
          'runs_without_pr': int,
        }
    """
    pr_groups: dict[int, list[dict]] = defaultdict(list)
    without_pr = 0

    for run in runs:
        pr_num = _parse_pr_number(run.get("event_params_blob", ""))
        if pr_num is not None:
            pr_groups[pr_num].append(run)
        else:
            without_pr += 1

    repo = _extract_repo(runs)
    commits_cache: dict[str, list] = {}
    use_github = bool(repo and github_token)

    pr_stats: dict[int, dict] = {}

    for pr_number, pr_runs in pr_groups.items():
        pr_runs.sort(key=lambda x: x.get("created_at", ""))

        merge_shas: set[str] = set()
        if use_github and repo and github_token:
            for commit in _fetch_pr_commits(repo, pr_number, github_token, commits_cache):
                msg = commit.get("commit", {}).get("message", "")
                if any(p.match(msg) for p in _MERGE_PATTERNS):
                    merge_shas.add(commit.get("sha", ""))

        sha_reruns = 0
        merge_reruns = 0
        rerun_details: list[dict] = []
        prev_sha: Optional[str] = None
        prev_run_id: Optional[str] = None

        for run in pr_runs:
            sha = _extract_head_sha(run.get("event_params_blob", ""))
            if not sha:
                continue
            dur = _calculate_duration(run.get("created_at", ""), run.get("updated_at", ""))
            run_id = run.get("id")

            if prev_sha and sha == prev_sha:
                sha_reruns += 1
                rerun_details.append(
                    {
                        "run_id": run_id,
                        "prev_run_id": prev_run_id,
                        "build_number": run.get("build_number"),
                        "status": run.get("status"),
                        "created_at": run.get("created_at"),
                        "duration": dur,
                        "commit_sha": sha[:12],
                        "rerun_type": "same_sha",
                    }
                )
            elif sha in merge_shas:
                merge_reruns += 1
                rerun_details.append(
                    {
                        "run_id": run_id,
                        "prev_run_id": prev_run_id,
                        "build_number": run.get("build_number"),
                        "status": run.get("status"),
                        "created_at": run.get("created_at"),
                        "duration": dur,
                        "commit_sha": sha[:12],
                        "rerun_type": "merge_commit",
                    }
                )
            prev_sha = sha
            prev_run_id = run_id

        total_reruns = sha_reruns + merge_reruns
        wasted = sum(r["duration"] for r in rerun_details)

        first = pr_runs[0]
        try:
            ep = json.loads(first.get("event_params_blob", "{}"))
            title = ep.get("pull_request", {}).get("title", "N/A")
            author = ep.get("pull_request", {}).get("user", {}).get("login", "N/A")
        except Exception:
            title = author = "N/A"

        pr_stats[pr_number] = {
            "total_runs": len(pr_runs),
            "rerun_count": total_reruns,
            "sha_rerun_count": sha_reruns,
            "merge_rerun_count": merge_reruns,
            "rerun_percentage": (total_reruns / len(pr_runs) * 100) if pr_runs else 0,
            "total_wasted_time": wasted,
            "dev_productivity_loss_minutes": total_reruns * 5,
            "rerun_details": rerun_details,
            "pr_title": title,
            "pr_author": author,
        }

    return {
        "pr_stats": pr_stats,
        "total_prs": len(pr_groups),
        "total_runs": len(runs),
        "runs_without_pr": without_pr,
    }
