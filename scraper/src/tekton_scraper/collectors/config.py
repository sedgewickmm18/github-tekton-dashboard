"""
Shared configuration dataclass for all collectors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _load_env_file(filepath: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
    return env


@dataclass
class PipelineConfig:
    api_key: str
    pipeline_id: str
    region: str
    trigger_name: str
    github_token: Optional[str] = None
    logs_base_dir: str = ""  # set by from_env_file; empty means "skip log analysis"
    pipeline_url: str = ""
    github_repo_url: str = ""

    @classmethod
    def from_env_file(cls, path: str | Path = "pipeline.env") -> "PipelineConfig":
        env_path = Path(path).resolve()
        env = _load_env_file(str(env_path))
        # Default logs dir: a "logs/" sibling of the env file (stable regardless of cwd)
        default_logs = str(env_path.parent / "logs")
        return cls(
            api_key=os.environ.get("IBM_CLOUD_API_KEY") or env.get("IBM_CLOUD_API_KEY", ""),
            pipeline_id=os.environ.get("PIPELINE_ID") or env.get("PIPELINE_ID", ""),
            region=os.environ.get("REGION") or env.get("REGION", ""),
            trigger_name=os.environ.get("TRIGGER_NAME") or env.get("TRIGGER_NAME", ""),
            github_token=(
                os.environ.get("GH_TOKEN")
                or os.environ.get("REPO_GITHUB_TOKEN")
                or os.environ.get("GITHUB_PAT")
                or os.environ.get("GITHUB_TOKEN")
                or env.get("GH_TOKEN")
                or env.get("REPO_GITHUB_TOKEN")
                or env.get("GITHUB_PAT")
                or env.get("GITHUB_TOKEN")
            ),
            logs_base_dir=os.environ.get("LOGS_BASE_DIR") or env.get("LOGS_BASE_DIR", default_logs),
            pipeline_url=os.environ.get("PIPELINE_URL") or env.get("PIPELINE_URL", ""),
            github_repo_url=os.environ.get("GITHUB_REPO_URL") or env.get("GITHUB_REPO_URL", ""),
        )

    def is_valid(self) -> bool:
        return bool(self.api_key and self.pipeline_id and self.region and self.trigger_name)
