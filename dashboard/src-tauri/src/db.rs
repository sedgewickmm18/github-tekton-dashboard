//! Storage backend dispatcher for Tauri commands.
//!
//! On first call, tries to open a Redis connection to FalkorDB.
//! If the TCP handshake succeeds → FalkorDB mode (GRAPH.RO_QUERY).
//! If it fails or TEKTON_BACKEND=sqlite → SQLite mode (~/.tekton-dashboard.db).
//!
//! TEKTON_BACKEND=falkordb forces FalkorDB (hard-fail if unreachable).
//! TEKTON_BACKEND=sqlite   forces SQLite.

use redis::{Client, RedisError, Value as RedisValue};
use serde_json::{json, Value};
use std::env;
use std::net::TcpStream;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// ─── Backend detection ────────────────────────────────────────────────────────

#[derive(Clone, Copy, PartialEq)]
enum Backend { FalkorDB, SQLite }

static BACKEND: OnceLock<Backend> = OnceLock::new();

fn active_backend() -> Backend {
    *BACKEND.get_or_init(|| {
        let forced = env::var("TEKTON_BACKEND").unwrap_or_default().to_lowercase();
        if forced == "sqlite"   { return Backend::SQLite; }
        if forced == "falkordb" { return Backend::FalkorDB; }

        // Probe FalkorDB port (1.5 s timeout)
        let host = env::var("FALKORDB_HOST").unwrap_or_else(|_| "127.0.0.1".into());
        let port: u16 = env::var("FALKORDB_PORT")
            .ok().and_then(|p| p.parse().ok()).unwrap_or(6379);
        let addr = format!("{}:{}", host, port);
        match TcpStream::connect_timeout(
            &addr.parse().unwrap_or("127.0.0.1:6379".parse().unwrap()),
            Duration::from_millis(1500),
        ) {
            Ok(_) => Backend::FalkorDB,
            Err(_) => Backend::SQLite,
        }
    })
}

// ─── FalkorDB helpers ─────────────────────────────────────────────────────────

fn graph_name() -> String {
    env::var("FALKORDB_GRAPH").unwrap_or_else(|_| "tekton-dashboard".to_string())
}

fn redis_url() -> String {
    let host = env::var("FALKORDB_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port = env::var("FALKORDB_PORT").unwrap_or_else(|_| "6379".to_string());
    format!("redis://{}:{}", host, port)
}

fn redis_to_json(rv: &RedisValue) -> Value {
    match rv {
        RedisValue::Nil => Value::Null,
        RedisValue::Int(i) => json!(i),
        RedisValue::BulkString(b) => match std::str::from_utf8(b) {
            Ok(s) => s.parse::<f64>().map(|n| json!(n)).unwrap_or_else(|_| json!(s)),
            Err(_) => Value::Null,
        },
        RedisValue::SimpleString(s) => json!(s),
        RedisValue::Array(arr) => Value::Array(arr.iter().map(redis_to_json).collect()),
        RedisValue::Boolean(b) => json!(b),
        RedisValue::Double(d) => json!(d),
        RedisValue::BigNumber(n) => json!(n.to_string()),
        RedisValue::Map(m) => {
            let mut obj = serde_json::Map::new();
            for (k, v) in m {
                let key = match k {
                    RedisValue::BulkString(b) => String::from_utf8_lossy(b).to_string(),
                    RedisValue::SimpleString(s) => s.clone(),
                    _ => format!("{:?}", k),
                };
                obj.insert(key, redis_to_json(v));
            }
            Value::Object(obj)
        }
        RedisValue::Set(s) => Value::Array(s.iter().map(redis_to_json).collect()),
        _ => Value::Null,
    }
}

fn cypher_ro(query: &str) -> Result<Value, String> {
    let client = Client::open(redis_url()).map_err(|e| e.to_string())?;
    let mut con = client.get_connection().map_err(|e| e.to_string())?;
    let raw: RedisValue = redis::cmd("GRAPH.RO_QUERY")
        .arg(&graph_name())
        .arg(query)
        .query(&mut con)
        .map_err(|e: RedisError| e.to_string())?;

    let outer = match &raw {
        RedisValue::Array(arr) => arr,
        _ => return Ok(json!([])),
    };
    if outer.len() < 2 { return Ok(json!([])); }

    let columns: Vec<String> = match &outer[0] {
        RedisValue::Array(cols) => cols.iter().map(|c| match c {
            RedisValue::BulkString(b) => String::from_utf8_lossy(b).to_string(),
            RedisValue::SimpleString(s) => s.clone(),
            _ => String::new(),
        }).collect(),
        _ => return Ok(json!([])),
    };

    let rows_rv = match &outer[1] {
        RedisValue::Array(r) => r,
        _ => return Ok(json!([])),
    };

    let rows: Vec<Value> = rows_rv.iter().map(|row| {
        let cells = match row { RedisValue::Array(c) => c.as_slice(), _ => &[] };
        let mut obj = serde_json::Map::new();
        for (i, col) in columns.iter().enumerate() {
            obj.insert(col.clone(), cells.get(i).map(redis_to_json).unwrap_or(Value::Null));
        }
        Value::Object(obj)
    }).collect();

    Ok(Value::Array(rows))
}

// ─── ISO 8601 cutoff helper ───────────────────────────────────────────────────

fn cutoff_iso(days: u32) -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH).unwrap_or_default()
        .as_secs().saturating_sub(days as u64 * 86400);
    let (y, mo, d, h, mi, sc) = epoch_to_ymd_hms(secs);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z", y, mo, d, h, mi, sc)
}

fn epoch_to_ymd_hms(epoch: u64) -> (u32, u32, u32, u32, u32, u32) {
    let sec  = (epoch % 60) as u32;
    let min  = ((epoch / 60) % 60) as u32;
    let hour = ((epoch / 3600) % 24) as u32;
    let mut days = epoch / 86400;
    let mut year = 1970u32;
    loop {
        let dy = if is_leap(year) { 366 } else { 365 };
        if days < dy { break; }
        days -= dy; year += 1;
    }
    let leap = is_leap(year);
    let months = [31u64, if leap { 29 } else { 28 }, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let mut month = 1u32;
    for &dm in &months {
        if days < dm { break; }
        days -= dm; month += 1;
    }
    (year, month, days as u32 + 1, hour, min, sec)
}
fn is_leap(y: u32) -> bool { (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0) }

// ─── Tauri commands — dispatch to active backend ──────────────────────────────

#[tauri::command]
pub fn get_summary(days: u32) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[:BELONGS_TO_PR]->(pr:PR)
            WHERE r.created_at >= '{cutoff}'
            WITH count(r) AS total_runs,
                 sum(CASE WHEN r.status='failed' THEN 1 ELSE 0 END) AS failed_runs,
                 count(DISTINCT pr) AS total_prs,
                 sum(r.duration_seconds) AS total_secs
            RETURN total_prs,
                   CASE WHEN total_runs > 0 THEN toFloat(failed_runs)/total_runs*100 ELSE 0 END AS failure_rate_pct,
                   total_secs/3600.0 AS compute_hours,
                   total_runs,
                   failed_runs"#, cutoff = cutoff))
    } else {
        crate::sqlite::get_summary(&cutoff)
    }
}

#[tauri::command]
pub fn get_pr_list(days: u32, status_filter: Option<String>) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        let status_clause = match status_filter.as_deref() {
            Some(s) => format!("AND r.status = '{}'", s),
            None => String::new(),
        };
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[:BELONGS_TO_PR]->(pr:PR)
            WHERE r.created_at >= '{cutoff}' {status_clause}
            RETURN pr.pr_number AS pr_number, count(r) AS total_runs,
                   sum(CASE WHEN r.status='failed'    THEN 1 ELSE 0 END) AS failed,
                   sum(CASE WHEN r.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
                   pr.author AS author, pr.title AS title
            ORDER BY total_runs DESC"#,
            cutoff = cutoff, status_clause = status_clause))
    } else {
        crate::sqlite::get_pr_list(&cutoff, status_filter.as_deref())
    }
}

#[tauri::command]
pub fn get_run_distribution(pr_number: u32) -> Result<Value, String> {
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[:BELONGS_TO_PR]->(pr:PR {{pr_number: {pr}}})
            RETURN r.run_id AS run_id, r.build_number AS build_number,
                   r.status AS status, r.created_at AS created_at,
                   r.duration_seconds AS duration_seconds, r.commit_sha AS commit_sha
            ORDER BY r.created_at"#, pr = pr_number))
    } else {
        crate::sqlite::get_run_distribution(pr_number)
    }
}

#[tauri::command]
pub fn get_error_breakdown(days: u32) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[:HAS_ERROR]->(e:ErrorType)
            WHERE r.created_at >= '{cutoff}'
            MATCH (r)-[:BELONGS_TO_PR]->(pr:PR)
            RETURN e.name AS error_type, count(r) AS occurrence_count,
                   count(DISTINCT pr) AS affected_prs
            ORDER BY occurrence_count DESC"#, cutoff = cutoff))
    } else {
        crate::sqlite::get_error_breakdown(&cutoff)
    }
}

#[tauri::command]
pub fn get_stage_failures(days: u32) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[e:HAS_STAGE]->(s:Stage)
            WHERE r.created_at >= '{cutoff}' AND e.status = 'failed'
            MATCH (r)-[:BELONGS_TO_PR]->(pr:PR)
            RETURN s.stage_id AS stage_name, count(r) AS failure_count,
                   count(DISTINCT pr) AS affected_prs
            ORDER BY failure_count DESC"#, cutoff = cutoff))
    } else {
        crate::sqlite::get_stage_failures(&cutoff)
    }
}

#[tauri::command]
pub fn get_rerun_stats(days: u32) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (rerun:Run)-[rel:IS_RERUN_OF]->(orig:Run)
            WHERE rerun.created_at >= '{cutoff}'
            MATCH (rerun)-[:BELONGS_TO_PR]->(pr:PR)
            RETURN pr.pr_number AS pr_number, count(rerun) AS rerun_count,
                   sum(COALESCE(rel.wasted_seconds, rerun.duration_seconds, 0)) AS wasted_seconds,
                   sum(CASE WHEN rel.rerun_type='same_sha'     THEN 1 ELSE 0 END) AS sha_rerun_count,
                   sum(CASE WHEN rel.rerun_type='merge_commit' THEN 1 ELSE 0 END) AS merge_rerun_count,
                   sum(CASE WHEN rel.rerun_type='same_sha'     THEN 5 ELSE 1 END) AS dev_loss_minutes
            ORDER BY rerun_count DESC"#, cutoff = cutoff))
    } else {
        crate::sqlite::get_rerun_stats(&cutoff)
    }
}

#[tauri::command]
pub fn get_pr_open_times(days: u32) -> Result<Value, String> {
    let cutoff = cutoff_iso(days);
    if active_backend() == Backend::FalkorDB {
        cypher_ro(&format!(
            r#"MATCH (r:Run)-[:BELONGS_TO_PR]->(pr:PR)
            WHERE r.created_at >= '{cutoff}'
            RETURN pr.pr_number AS pr_number, pr.created_at AS pr_created_at,
                   max(r.created_at) AS last_run_at, pr.author AS author,
                   count(r) AS total_runs
            ORDER BY pr_number"#, cutoff = cutoff))
    } else {
        crate::sqlite::get_pr_open_times(&cutoff)
    }
}

#[tauri::command]
pub fn get_scrape_meta() -> Result<Value, String> {
    if active_backend() == Backend::FalkorDB {
        cypher_ro("MATCH (m:ScrapeMeta {key:'latest'}) RETURN m.last_scraped_at AS last_scraped_at, m.run_count AS run_count, m.days AS days")
    } else {
        crate::sqlite::get_scrape_meta()
    }
}
