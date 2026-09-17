"""
Writer facade — dispatches to FalkorDB or SQLite based on active_backend().
"""
from __future__ import annotations

import logging
from typing import Any

from tekton_scraper.db.client import active_backend, get_graph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _falkordb_query(query: str, params: dict[str, Any] | None = None) -> None:
    get_graph().query(query, params or {})


def _sqlite():
    from tekton_scraper.db import sqlite_backend
    return sqlite_backend


# ---------------------------------------------------------------------------
# Pipeline node
# ---------------------------------------------------------------------------

def upsert_pipeline(pipeline_id: str, name: str, region: str, trigger_name: str) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            MERGE (p:Pipeline {pipeline_id: $pipeline_id})
            ON CREATE SET p.name=$name, p.region=$region, p.trigger_name=$trigger_name
            ON MATCH  SET p.name=$name, p.region=$region, p.trigger_name=$trigger_name
            """,
            {"pipeline_id": pipeline_id, "name": name,
             "region": region, "trigger_name": trigger_name},
        )
    else:
        _sqlite().upsert_pipeline(pipeline_id, name, region, trigger_name)


# ---------------------------------------------------------------------------
# PR nodes
# ---------------------------------------------------------------------------

def upsert_prs(pr_list: list[dict[str, Any]]) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            UNWIND $prs AS pr
            MERGE (p:PR {pr_number: pr.pr_number})
            ON CREATE SET p.title=pr.title, p.author=pr.author,
                          p.url=pr.url, p.created_at=pr.created_at
            ON MATCH  SET p.title=pr.title, p.author=pr.author,
                          p.url=pr.url, p.created_at=pr.created_at
            """,
            {"prs": pr_list},
        )
    else:
        _sqlite().upsert_prs(pr_list)


# ---------------------------------------------------------------------------
# Run nodes + edges
# ---------------------------------------------------------------------------

def upsert_runs(pipeline_id: str, runs: list[dict[str, Any]]) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            UNWIND $runs AS r
            MERGE (run:Run {run_id: r.run_id})
            ON CREATE SET run.build_number=r.build_number, run.status=r.status,
                          run.created_at=r.created_at, run.updated_at=r.updated_at,
                          run.duration_seconds=r.duration_seconds, run.commit_sha=r.commit_sha
            ON MATCH  SET run.status=r.status, run.updated_at=r.updated_at,
                          run.duration_seconds=r.duration_seconds

            WITH run, r
            MATCH (pipe:Pipeline {pipeline_id: $pipeline_id})
            MERGE (pipe)-[:HAS_RUN]->(run)

            WITH run, r
            WHERE r.pr_number IS NOT NULL
            MERGE (pr:PR {pr_number: r.pr_number})
            MERGE (run)-[:BELONGS_TO_PR]->(pr)

            WITH run, r
            WHERE r.pr_author IS NOT NULL
            MERGE (dev:Developer {login: r.pr_author})
            MERGE (run)-[:AUTHORED_BY]->(dev)
            """,
            {"runs": runs, "pipeline_id": pipeline_id},
        )
    else:
        _sqlite().upsert_runs(pipeline_id, runs)


# ---------------------------------------------------------------------------
# Stage failures
# ---------------------------------------------------------------------------

def upsert_stages(run_stage_list: list[dict[str, Any]]) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            UNWIND $items AS item
            MATCH (run:Run {run_id: item.run_id})
            MERGE (s:Stage {stage_id: item.stage_name})
            MERGE (run)-[e:HAS_STAGE]->(s)
            SET e.status=item.status, e.reason=item.reason
            """,
            {"items": run_stage_list},
        )
    else:
        _sqlite().upsert_stages(run_stage_list)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------

def upsert_errors(run_error_list: list[dict[str, Any]]) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            UNWIND $items AS item
            MATCH (run:Run {run_id: item.run_id})
            MERGE (e:ErrorType {name: item.error_type})
            MERGE (run)-[:HAS_ERROR]->(e)
            """,
            {"items": run_error_list},
        )
    else:
        _sqlite().upsert_errors(run_error_list)


# ---------------------------------------------------------------------------
# Reruns
# ---------------------------------------------------------------------------

def upsert_reruns(rerun_pairs: list[dict[str, Any]]) -> None:
    if active_backend() == "falkordb":
        _falkordb_query(
            """
            UNWIND $pairs AS pair
            MATCH (rerun:Run {run_id: pair.run_id})
            MERGE (orig:Run  {run_id: pair.prev_run_id})
            MERGE (rerun)-[r:IS_RERUN_OF]->(orig)
            SET r.rerun_type=pair.rerun_type,
                r.wasted_seconds=pair.wasted_seconds
            """,
            {"pairs": rerun_pairs},
        )
    else:
        _sqlite().upsert_reruns(rerun_pairs)
