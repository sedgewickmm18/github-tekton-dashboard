"""
SQLite backend for Tekton Dashboard — used when FalkorDB is not available.

All data is stored in a single SQLite file (default: ~/.tekton-dashboard.db
or overridden via TEKTON_SQLITE_PATH env var).

The table layout mirrors the FalkorDB graph schema so the same analysis
dicts produced by the collector modules can be written to either backend.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".tekton-dashboard.db"


def db_path() -> Path:
    return Path(os.environ.get("TEKTON_SQLITE_PATH", str(_DEFAULT_PATH)))


@lru_cache(maxsize=1)
def _get_connection() -> sqlite3.Connection:
    path = db_path()
    logger.info("SQLite backend: %s", path)
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def _cursor() -> Generator[sqlite3.Cursor, None, None]:
    con = _get_connection()
    cur = con.cursor()
    try:
        yield cur
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    pipeline_id  TEXT PRIMARY KEY,
    name         TEXT,
    region       TEXT,
    trigger_name TEXT
);

CREATE TABLE IF NOT EXISTS prs (
    pr_number  INTEGER PRIMARY KEY,
    title      TEXT,
    author     TEXT,
    url        TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    pipeline_id      TEXT,
    pr_number        INTEGER,
    build_number     INTEGER,
    status           TEXT,
    created_at       TEXT,
    updated_at       TEXT,
    duration_seconds REAL,
    commit_sha       TEXT,
    pr_author        TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_runs_pr_number  ON runs(pr_number);
CREATE INDEX IF NOT EXISTS idx_runs_pipeline   ON runs(pipeline_id);

CREATE TABLE IF NOT EXISTS run_stages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status    TEXT,
    reason    TEXT,
    UNIQUE(run_id, stage_name)
);

CREATE TABLE IF NOT EXISTS run_errors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    error_type TEXT NOT NULL,
    UNIQUE(run_id, error_type)
);

CREATE TABLE IF NOT EXISTS reruns (
    run_id         TEXT NOT NULL,
    prev_run_id    TEXT NOT NULL,
    rerun_type     TEXT,
    wasted_seconds REAL DEFAULT 0.0,
    PRIMARY KEY (run_id, prev_run_id)
);

CREATE TABLE IF NOT EXISTS scrape_meta (
    key              TEXT PRIMARY KEY,
    last_scraped_at  TEXT,
    run_count        INTEGER,
    days             INTEGER,
    pipeline_url     TEXT,
    github_repo_url  TEXT
);
"""


def migrate() -> None:
    """Create all tables if they don't exist, and add new columns to existing ones."""
    with _cursor() as cur:
        cur.executescript(_SCHEMA_SQL)
        # Add columns introduced after the initial schema — safe to run repeatedly.
        for stmt in [
            "ALTER TABLE scrape_meta ADD COLUMN pipeline_url TEXT",
            "ALTER TABLE scrape_meta ADD COLUMN github_repo_url TEXT",
        ]:
            try:
                cur.execute(stmt)
            except Exception:
                pass  # column already exists
    logger.info("SQLite migration complete: %s", db_path())


# ---------------------------------------------------------------------------
# Writers — same signatures as db/writer.py
# ---------------------------------------------------------------------------

def upsert_pipeline(pipeline_id: str, name: str, region: str, trigger_name: str) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipelines(pipeline_id, name, region, trigger_name)
            VALUES(?,?,?,?)
            ON CONFLICT(pipeline_id) DO UPDATE SET
                name=excluded.name, region=excluded.region,
                trigger_name=excluded.trigger_name
            """,
            (pipeline_id, name, region, trigger_name),
        )


def upsert_prs(pr_list: list[dict[str, Any]]) -> None:
    with _cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prs(pr_number, title, author, url, created_at)
            VALUES(:pr_number,:title,:author,:url,:created_at)
            ON CONFLICT(pr_number) DO UPDATE SET
                title=excluded.title, author=excluded.author,
                url=excluded.url, created_at=excluded.created_at
            """,
            pr_list,
        )


def upsert_runs(pipeline_id: str, runs: list[dict[str, Any]]) -> None:
    rows = [{**r, "pipeline_id": pipeline_id} for r in runs]
    with _cursor() as cur:
        cur.executemany(
            """
            INSERT INTO runs(run_id, pipeline_id, pr_number, build_number, status,
                             created_at, updated_at, duration_seconds, commit_sha, pr_author)
            VALUES(:run_id,:pipeline_id,:pr_number,:build_number,:status,
                   :created_at,:updated_at,:duration_seconds,:commit_sha,:pr_author)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status, updated_at=excluded.updated_at,
                duration_seconds=excluded.duration_seconds
            """,
            rows,
        )


def upsert_stages(run_stage_list: list[dict[str, Any]]) -> None:
    with _cursor() as cur:
        cur.executemany(
            """
            INSERT INTO run_stages(run_id, stage_name, status, reason)
            VALUES(:run_id,:stage_name,:status,:reason)
            ON CONFLICT(run_id, stage_name) DO UPDATE SET
                status=excluded.status, reason=excluded.reason
            """,
            run_stage_list,
        )


def upsert_errors(run_error_list: list[dict[str, Any]]) -> None:
    with _cursor() as cur:
        cur.executemany(
            """
            INSERT OR IGNORE INTO run_errors(run_id, error_type)
            VALUES(:run_id,:error_type)
            """,
            run_error_list,
        )


def upsert_reruns(rerun_pairs: list[dict[str, Any]]) -> None:
    with _cursor() as cur:
        cur.executemany(
            """
            INSERT INTO reruns(run_id, prev_run_id, rerun_type, wasted_seconds)
            VALUES(:run_id,:prev_run_id,:rerun_type,:wasted_seconds)
            ON CONFLICT(run_id, prev_run_id) DO UPDATE SET
                rerun_type=excluded.rerun_type,
                wasted_seconds=excluded.wasted_seconds
            """,
            rerun_pairs,
        )


def upsert_scrape_meta(
    last_scraped_at: str,
    run_count: int,
    days: int,
    pipeline_url: str = "",
    github_repo_url: str = "",
) -> None:
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_meta(key, last_scraped_at, run_count, days,
                                    pipeline_url, github_repo_url)
            VALUES('latest',?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                last_scraped_at=excluded.last_scraped_at,
                run_count=excluded.run_count,
                days=excluded.days,
                pipeline_url=excluded.pipeline_url,
                github_repo_url=excluded.github_repo_url
            """,
            (last_scraped_at, run_count, days, pipeline_url, github_repo_url),
        )


# ---------------------------------------------------------------------------
# Readers — used by the Tauri backend via a thin JSON-over-stdin/stdout
# protocol, or directly by tests.
# ---------------------------------------------------------------------------

def _rows_as_dicts(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_summary(cutoff: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT pr_number)                          AS total_prs,
                CAST(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS REAL)
                    / MAX(COUNT(*), 1) * 100                       AS failure_rate_pct,
                SUM(duration_seconds) / 3600.0                     AS compute_hours,
                NULL                                               AS placeholder
            FROM runs
            WHERE created_at >= ?
            """,
            (cutoff,),
        )
        return _rows_as_dicts(cur)


def query_pr_list(cutoff: str, status_filter: str | None = None) -> list[dict[str, Any]]:
    where = "r.created_at >= ?"
    params: list[Any] = [cutoff]
    if status_filter:
        where += " AND r.status = ?"
        params.append(status_filter)
    with _cursor() as cur:
        cur.execute(
            f"""
            SELECT r.pr_number,
                   COUNT(*) AS total_runs,
                   SUM(CASE WHEN r.status='failed'    THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN r.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                   p.author,
                   p.title
            FROM runs r
            LEFT JOIN prs p ON p.pr_number = r.pr_number
            WHERE {where}
            GROUP BY r.pr_number
            ORDER BY total_runs DESC
            """,
            params,
        )
        return _rows_as_dicts(cur)


def query_run_distribution(pr_number: int) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT run_id, build_number, status, created_at,
                   duration_seconds, commit_sha
            FROM runs
            WHERE pr_number = ?
            ORDER BY created_at
            """,
            (pr_number,),
        )
        return _rows_as_dicts(cur)


def query_error_breakdown(cutoff: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT e.error_type,
                   COUNT(*) AS occurrence_count,
                   COUNT(DISTINCT r.pr_number) AS affected_prs
            FROM run_errors e
            JOIN runs r ON r.run_id = e.run_id
            WHERE r.created_at >= ?
            GROUP BY e.error_type
            ORDER BY occurrence_count DESC
            """,
            (cutoff,),
        )
        return _rows_as_dicts(cur)


def query_stage_failures(cutoff: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT s.stage_name,
                   COUNT(*) AS failure_count,
                   COUNT(DISTINCT r.pr_number) AS affected_prs
            FROM run_stages s
            JOIN runs r ON r.run_id = s.run_id
            WHERE s.status = 'failed'
              AND r.created_at >= ?
            GROUP BY s.stage_name
            ORDER BY failure_count DESC
            """,
            (cutoff,),
        )
        return _rows_as_dicts(cur)


def query_rerun_stats(cutoff: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT r.pr_number,
                   COUNT(*) AS rerun_count,
                   SUM(r.duration_seconds) AS wasted_seconds,
                   COUNT(*) * 5 AS dev_loss_minutes
            FROM reruns rr
            JOIN runs r ON r.run_id = rr.run_id
            WHERE r.created_at >= ?
            GROUP BY r.pr_number
            ORDER BY rerun_count DESC
            """,
            (cutoff,),
        )
        return _rows_as_dicts(cur)


def query_pr_open_times(cutoff: str) -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """
            SELECT r.pr_number,
                   p.created_at AS pr_created_at,
                   MAX(r.created_at) AS last_run_at,
                   p.author,
                   COUNT(*) AS total_runs
            FROM runs r
            LEFT JOIN prs p ON p.pr_number = r.pr_number
            WHERE r.created_at >= ?
            GROUP BY r.pr_number
            ORDER BY r.pr_number
            """,
            (cutoff,),
        )
        return _rows_as_dicts(cur)


def query_scrape_meta() -> list[dict[str, Any]]:
    with _cursor() as cur:
        cur.execute(
            """SELECT last_scraped_at, run_count, days,
                      pipeline_url, github_repo_url
               FROM scrape_meta WHERE key='latest'"""
        )
        return _rows_as_dicts(cur)
