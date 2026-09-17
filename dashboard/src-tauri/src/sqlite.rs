//! SQLite query backend — mirrors all functions in db.rs but reads from the
//! local ~/.tekton-dashboard.db file (same path the Python scraper writes to).

use rusqlite::{params, Connection, Result as SqlResult, Row};
use serde_json::{json, Map, Value};
use std::env;
use std::path::PathBuf;

fn db_path() -> PathBuf {
    if let Ok(p) = env::var("TEKTON_SQLITE_PATH") {
        return PathBuf::from(p);
    }
    dirs_home().join(".tekton-dashboard.db")
}

fn dirs_home() -> PathBuf {
    // Simple cross-platform home dir without extra crates
    env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn open() -> SqlResult<Connection> {
    let con = Connection::open(db_path())?;
    con.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
    Ok(con)
}

/// Convert a SQLite row to a JSON object given a list of column names.
fn row_to_json(row: &Row, columns: &[&str]) -> Value {
    let mut map = Map::new();
    for (i, col) in columns.iter().enumerate() {
        let v: Value = row
            .get::<_, rusqlite::types::Value>(i)
            .map(|rv| match rv {
                rusqlite::types::Value::Null => Value::Null,
                rusqlite::types::Value::Integer(n) => json!(n),
                rusqlite::types::Value::Real(f) => json!(f),
                rusqlite::types::Value::Text(s) => json!(s),
                rusqlite::types::Value::Blob(b) => {
                    json!(String::from_utf8_lossy(&b).to_string())
                }
            })
            .unwrap_or(Value::Null);
        map.insert(col.to_string(), v);
    }
    Value::Object(map)
}

// ─── Query functions ──────────────────────────────────────────────────────────

pub fn get_summary(cutoff: &str) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["total_prs", "failure_rate_pct", "compute_hours", "total_runs", "failed_runs"];
    let row: Value = con
        .query_row(
            r#"
            SELECT
                COUNT(DISTINCT pr_number)                                             AS total_prs,
                CAST(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS REAL)
                    / MAX(COUNT(*), 1) * 100                                         AS failure_rate_pct,
                SUM(duration_seconds) / 3600.0                                       AS compute_hours,
                COUNT(*)                                                              AS total_runs,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END)                     AS failed_runs
            FROM runs WHERE created_at >= ?1
            "#,
            params![cutoff],
            |row| Ok(row_to_json(row, cols)),
        )
        .map_err(|e| e.to_string())?;
    Ok(Value::Array(vec![row]))
}

pub fn get_pr_list(cutoff: &str, status_filter: Option<&str>) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["pr_number", "total_runs", "failed", "succeeded", "author", "title"];
    let sql = format!(
        r#"
        SELECT r.pr_number,
               COUNT(*) AS total_runs,
               SUM(CASE WHEN r.status='failed'    THEN 1 ELSE 0 END) AS failed,
               SUM(CASE WHEN r.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
               p.author, p.title
        FROM runs r
        LEFT JOIN prs p ON p.pr_number = r.pr_number
        WHERE r.created_at >= ?1 {status}
        GROUP BY r.pr_number
        ORDER BY total_runs DESC
        "#,
        status = match status_filter {
            Some(s) => format!("AND r.status = '{}'", s),
            None => String::new(),
        }
    );
    let mut stmt = con.prepare(&sql).map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![cutoff], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_run_distribution(pr_number: u32) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["run_id", "build_number", "status", "created_at", "duration_seconds", "commit_sha"];
    let mut stmt = con
        .prepare(
            r#"
            SELECT run_id, build_number, status, created_at, duration_seconds, commit_sha
            FROM runs WHERE pr_number = ?1 ORDER BY created_at
            "#,
        )
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![pr_number], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_error_breakdown(cutoff: &str) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["error_type", "occurrence_count", "affected_prs"];
    let mut stmt = con
        .prepare(
            r#"
            SELECT e.error_type, COUNT(*) AS occurrence_count,
                   COUNT(DISTINCT r.pr_number) AS affected_prs
            FROM run_errors e
            JOIN runs r ON r.run_id = e.run_id
            WHERE r.created_at >= ?1
            GROUP BY e.error_type ORDER BY occurrence_count DESC
            "#,
        )
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![cutoff], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_stage_failures(cutoff: &str) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["stage_name", "failure_count", "affected_prs"];
    let mut stmt = con
        .prepare(
            r#"
            SELECT s.stage_name, COUNT(*) AS failure_count,
                   COUNT(DISTINCT r.pr_number) AS affected_prs
            FROM run_stages s
            JOIN runs r ON r.run_id = s.run_id
            WHERE s.status = 'failed' AND r.created_at >= ?1
            GROUP BY s.stage_name ORDER BY failure_count DESC
            "#,
        )
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![cutoff], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_rerun_stats(cutoff: &str) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["pr_number", "rerun_count", "wasted_seconds", "sha_rerun_count", "merge_rerun_count", "dev_loss_minutes"];
    let mut stmt = con
        .prepare(
            r#"
            SELECT r.pr_number,
                   COUNT(*) AS rerun_count,
                   SUM(COALESCE(rr.wasted_seconds, r.duration_seconds, 0)) AS wasted_seconds,
                   SUM(CASE WHEN rr.rerun_type='same_sha'     THEN 1 ELSE 0 END) AS sha_rerun_count,
                   SUM(CASE WHEN rr.rerun_type='merge_commit' THEN 1 ELSE 0 END) AS merge_rerun_count,
                   SUM(CASE WHEN rr.rerun_type='same_sha'     THEN 5 ELSE 1 END) AS dev_loss_minutes
            FROM reruns rr
            JOIN runs r ON r.run_id = rr.run_id
            WHERE r.created_at >= ?1
            GROUP BY r.pr_number ORDER BY rerun_count DESC
            "#,
        )
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![cutoff], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_pr_open_times(cutoff: &str) -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["pr_number", "pr_created_at", "last_run_at", "author", "total_runs"];
    let mut stmt = con
        .prepare(
            r#"
            SELECT r.pr_number, p.created_at AS pr_created_at,
                   MAX(r.created_at) AS last_run_at, p.author, COUNT(*) AS total_runs
            FROM runs r
            LEFT JOIN prs p ON p.pr_number = r.pr_number
            WHERE r.created_at >= ?1
            GROUP BY r.pr_number ORDER BY r.pr_number
            "#,
        )
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map(params![cutoff], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}

pub fn get_scrape_meta() -> Result<Value, String> {
    let con = open().map_err(|e| e.to_string())?;
    let cols = &["last_scraped_at", "run_count", "days"];
    let mut stmt = con
        .prepare("SELECT last_scraped_at, run_count, days FROM scrape_meta WHERE key='latest'")
        .map_err(|e| e.to_string())?;
    let rows: Vec<Value> = stmt
        .query_map([], |row| Ok(row_to_json(row, cols)))
        .map_err(|e| e.to_string())?
        .filter_map(|r| r.ok())
        .collect();
    Ok(Value::Array(rows))
}
