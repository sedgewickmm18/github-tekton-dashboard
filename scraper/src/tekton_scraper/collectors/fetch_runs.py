"""
fetch_runs — importable module wrapping fetch-pr-builds.py logic.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from tekton_scraper.collectors.config import PipelineConfig


def get_access_token(config: PipelineConfig) -> str:
    """Obtain an IBM Cloud IAM Bearer token."""
    url = "https://iam.cloud.ibm.com/identity/token"
    post_data = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={config.api_key}"
    req = urllib.request.Request(
        url,
        data=post_data.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        return data["access_token"]


def _fetch_page(
    config: PipelineConfig,
    token: str,
    start_token: Optional[str] = None,
) -> dict:
    encoded = urllib.parse.quote(config.trigger_name)
    path = (
        f"/pipeline/v2/tekton_pipelines/{config.pipeline_id}"
        f"/pipeline_runs?trigger.name={encoded}&limit=100"
    )
    if start_token:
        path += f"&start={start_token}"
    url = f"https://api.{config.region}.devops.cloud.ibm.com{path}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def fetch_runs(
    config: PipelineConfig,
    days: int = 30,
    pr_number: Optional[int] = None,
    token: Optional[str] = None,
) -> tuple[list[dict], str]:
    """
    Fetch pipeline runs from IBM Cloud for the last *days* days.

    Args:
        config:     PipelineConfig instance.
        days:       How far back to look.
        pr_number:  If set, client-side filter to a single PR.
        token:      Pre-fetched IAM Bearer token.  If omitted, one is fetched.

    Returns:
        Tuple of (runs, token) so callers can reuse the token for subsequent
        API calls without an extra IAM round-trip.
    """
    if token is None:
        token = get_access_token(config)
    cutoff = datetime.now() - timedelta(days=days)
    all_runs: list[dict] = []
    next_token: Optional[str] = None

    for _ in range(100):  # page limit
        page = _fetch_page(config, token, next_token)
        page_runs = page.get("pipeline_runs", [])
        recent = []
        for run in page_runs:
            ts = run.get("created_at", "")
            if ts:
                run_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if run_dt.replace(tzinfo=None) >= cutoff:
                    recent.append(run)
        all_runs.extend(recent)
        if len(recent) < len(page_runs):
            break
        next_token = page.get("next", {}).get("start")
        if not next_token:
            break

    if pr_number is not None:
        filtered = []
        for run in all_runs:
            try:
                ep = json.loads(run.get("event_params_blob", "{}"))
                if ep.get("number") == pr_number:
                    filtered.append(run)
            except Exception:
                pass
        return filtered, token

    return all_runs, token
