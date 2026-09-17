#!/usr/bin/env python3
"""
cleanup_pipeline.py — Remove all data for a specific Tekton pipeline from
FalkorDB or SQLite.

Usage:
    uv run python cleanup_pipeline.py --pipeline-id <ID> [--env pipeline.env] [--dry-run]
    uv run python cleanup_pipeline.py --all          [--env pipeline.env] [--dry-run]

  --pipeline-id  Only delete nodes/rows belonging to this pipeline ID.
  --all          Wipe every pipeline's data (full reset).
  --dry-run      Print what would be deleted without actually deleting.
  --env          Path to pipeline.env (used only to detect the backend).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_backend() -> str:
    forced = os.environ.get("TEKTON_BACKEND", "").lower()
    if forced in ("sqlite", "falkordb"):
        return forced
    # TCP probe on the FalkorDB port
    import socket
    host = os.environ.get("FALKORDB_HOST", "127.0.0.1")
    port = int(os.environ.get("FALKORDB_PORT", "6379"))
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return "falkordb"
    except OSError:
        return "sqlite"


def _graph_name() -> str:
    return os.environ.get("FALKORDB_GRAPH", "tekton-dashboard")


def _redis_url() -> str:
    host = os.environ.get("FALKORDB_HOST", "127.0.0.1")
    port = os.environ.get("FALKORDB_PORT", "6379")
    return f"redis://{host}:{port}"


def _sqlite_path() -> Path:
    env = os.environ.get("TEKTON_SQLITE_PATH")
    if env:
        return Path(env)
    return Path.home() / ".tekton-dashboard.db"


# ---------------------------------------------------------------------------
# FalkorDB cleanup
# ---------------------------------------------------------------------------

def _falkordb_cleanup(pipeline_id: str | None, dry_run: bool) -> None:
    """Delete graph nodes tied to *pipeline_id*, or all nodes if pipeline_id is None."""
    try:
        import redis as _redis
    except ImportError:
        sys.exit("redis-py is not installed. Run: uv add redis")

    client = _redis.from_url(_redis_url())
    graph = _graph_name()

    if pipeline_id:
        queries = [
            # Remove HAS_STAGE edges for failed runs of this pipeline
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}})-[:HAS_RUN]->(r:Run) "
            "MATCH (r)-[e:HAS_STAGE]->() DELETE e",
            # Remove HAS_ERROR edges
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}})-[:HAS_RUN]->(r:Run) "
            "MATCH (r)-[e:HAS_ERROR]->() DELETE e",
            # Remove IS_RERUN_OF edges
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}})-[:HAS_RUN]->(r:Run) "
            "MATCH (r)-[e:IS_RERUN_OF]->() DELETE e",
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}})-[:HAS_RUN]->(r:Run) "
            "MATCH ()-[e:IS_RERUN_OF]->(r) DELETE e",
            # Remove run → PR / developer edges and Run nodes
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}})-[:HAS_RUN]->(r:Run) "
            "DETACH DELETE r",
            # Remove the Pipeline node itself
            f"MATCH (pipe:Pipeline {{pipeline_id:'{pipeline_id}'}}) DETACH DELETE pipe",
            # Clean up orphan PR nodes (PRs with no runs left)
            "MATCH (pr:PR) WHERE NOT (()-[:BELONGS_TO_PR]->(pr)) DETACH DELETE pr",
            # Clean up orphan Stage / ErrorType nodes
            "MATCH (s:Stage) WHERE NOT (()-[:HAS_STAGE]->(s)) DELETE s",
            "MATCH (e:ErrorType) WHERE NOT (()-[:HAS_ERROR]->(e)) DELETE e",
            # Clean up orphan Developer nodes
            "MATCH (d:Developer) WHERE NOT (()-[:AUTHORED_BY]->(d)) DELETE d",
        ]
        label = f"pipeline '{pipeline_id}'"
    else:
        queries = [
            "MATCH (n) DETACH DELETE n",
        ]
        label = "ALL data"

    if dry_run:
        print(f"[dry-run] Would delete {label} from FalkorDB graph '{graph}'")
        for q in queries:
            print(f"  QUERY: {q[:120]}…" if len(q) > 120 else f"  QUERY: {q}")
        return

    for q in queries:
        client.execute_command("GRAPH.QUERY", graph, q)
    print(f"✓ Deleted {label} from FalkorDB graph '{graph}'")


# ---------------------------------------------------------------------------
# SQLite cleanup
# ---------------------------------------------------------------------------

def _sqlite_cleanup(pipeline_id: str | None, dry_run: bool) -> None:
    import sqlite3
    path = _sqlite_path()
    if not path.exists():
        print(f"SQLite DB not found at {path} — nothing to do.")
        return

    con = sqlite3.connect(str(path))
    con.execute("PRAGMA foreign_keys=ON")

    if pipeline_id:
        label = f"pipeline '{pipeline_id}'"
        if dry_run:
            cur = con.execute("SELECT COUNT(*) FROM runs WHERE pipeline_id=?", (pipeline_id,))
            n = cur.fetchone()[0]
            print(f"[dry-run] Would delete {n} runs (and all related data) for {label} from {path}")
            con.close()
            return
        # Delete dependent rows first
        con.execute(
            "DELETE FROM reruns WHERE run_id IN (SELECT run_id FROM runs WHERE pipeline_id=?)",
            (pipeline_id,),
        )
        for tbl in ["run_stages", "run_errors"]:
            con.execute(
                f"DELETE FROM {tbl} WHERE run_id IN (SELECT run_id FROM runs WHERE pipeline_id=?)",
                (pipeline_id,),
            )
        # Collect PR numbers to clean up orphans after run deletion
        prs = {r[0] for r in con.execute(
            "SELECT DISTINCT pr_number FROM runs WHERE pipeline_id=?", (pipeline_id,)
        )}
        con.execute("DELETE FROM runs WHERE pipeline_id=?", (pipeline_id,))
        con.execute("DELETE FROM pipelines WHERE pipeline_id=?", (pipeline_id,))
        # Remove PRs that no longer have any runs
        for pr_num in prs:
            remaining = con.execute(
                "SELECT COUNT(*) FROM runs WHERE pr_number=?", (pr_num,)
            ).fetchone()[0]
            if remaining == 0:
                con.execute("DELETE FROM prs WHERE pr_number=?", (pr_num,))
    else:
        label = "ALL data"
        if dry_run:
            cur = con.execute("SELECT COUNT(*) FROM runs")
            n = cur.fetchone()[0]
            print(f"[dry-run] Would delete {n} runs (all tables) from {path}")
            con.close()
            return
        for tbl in ["reruns", "run_stages", "run_errors", "runs", "prs", "pipelines", "scrape_meta"]:
            con.execute(f"DELETE FROM {tbl}")

    con.commit()
    con.close()
    print(f"✓ Deleted {label} from SQLite DB at {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up Tekton pipeline data from FalkorDB or SQLite")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pipeline-id", help="Pipeline ID whose data should be deleted")
    group.add_argument("--all", action="store_true", help="Wipe all pipeline data (full reset)")
    parser.add_argument("--env", default="pipeline.env", help="Path to pipeline.env (for backend detection)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted without deleting")
    args = parser.parse_args()

    # Load env file if it exists (sets TEKTON_BACKEND etc.)
    env_path = Path(args.env)
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

    pipeline_id: str | None = args.pipeline_id if not args.all else None
    backend = _active_backend()
    print(f"Backend: {backend}")

    if backend == "falkordb":
        _falkordb_cleanup(pipeline_id, args.dry_run)
    else:
        _sqlite_cleanup(pipeline_id, args.dry_run)


if __name__ == "__main__":
    main()
