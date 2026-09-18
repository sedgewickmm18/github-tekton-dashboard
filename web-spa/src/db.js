import initSqlJs from 'sql.js'

let dbInstance = null

/**
 * Initialize sql.js, fetch the SQLite database binary, and instantiate the DB handle.
 * Resolves db file path using import.meta.env.BASE_URL.
 */
export async function initDb() {
  if (dbInstance) return dbInstance

  const baseUrl = import.meta.env.BASE_URL || '/'
  // Ensure trailing slash on base URL for path joining
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl : baseUrl + '/'

  const SQL = await initSqlJs({
    locateFile: file => {
      const cleanFile = file.startsWith('/') ? file.slice(1) : file
      return `${normalizedBase}${cleanFile}`
    }
  })

  const dbUrl = `${normalizedBase}dashboard.db`
  const res = await fetch(dbUrl)
  if (!res.ok) {
    throw new Error(`Failed to load database from ${dbUrl}: HTTP ${res.status} ${res.statusText}`)
  }

  const buf = await res.arrayBuffer()
  dbInstance = new SQL.Database(new Uint8Array(buf))
  return dbInstance
}

/**
 * Execute a SQL query with optional parameters, returning an array of objects (col -> val).
 */
export function query(sql, params = []) {
  if (!dbInstance) {
    throw new Error('Database is not initialized. Call initDb() first.')
  }

  const stmt = dbInstance.prepare(sql)
  if (params && params.length > 0) {
    stmt.bind(params)
  }

  const results = []
  while (stmt.step()) {
    results.push(stmt.getAsObject())
  }
  stmt.free()
  return results
}

/**
 * Compute ISO cutoff date string given days in the past.
 */
function getCutoff(days) {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString()
}

// ─── Query Helpers mirroring backend API ──────────────────────────────────────

export async function getSummary({ days = 30 } = {}) {
  const cutoff = getCutoff(days)
  const sql = `
    SELECT
      COUNT(DISTINCT pr_number) AS total_prs,
      CAST(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS REAL)
        / MAX(COUNT(*), 1) * 100 AS failure_rate_pct,
      SUM(duration_seconds) / 3600.0 AS compute_hours,
      COUNT(*) AS total_runs,
      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_runs
    FROM runs
    WHERE created_at >= ?
  `
  return query(sql, [cutoff])
}

export async function getPrList({ days = 30, statusFilter = null } = {}) {
  const cutoff = getCutoff(days)
  let sql = `
    SELECT r.pr_number,
           COUNT(*) AS total_runs,
           SUM(CASE WHEN r.status='failed'    THEN 1 ELSE 0 END) AS failed,
           SUM(CASE WHEN r.status='succeeded' THEN 1 ELSE 0 END) AS succeeded,
           p.author, p.title
    FROM runs r
    LEFT JOIN prs p ON p.pr_number = r.pr_number
    WHERE r.created_at >= ?
  `
  const params = [cutoff]
  if (statusFilter) {
    sql += ' AND r.status = ?'
    params.push(statusFilter)
  }
  sql += `
    GROUP BY r.pr_number
    ORDER BY total_runs DESC
  `
  return query(sql, params)
}

export async function getRunDistribution({ prNumber }) {
  const sql = `
    SELECT run_id, build_number, status, created_at, duration_seconds, commit_sha
    FROM runs
    WHERE pr_number = ?
    ORDER BY created_at
  `
  return query(sql, [prNumber])
}

export async function getErrorBreakdown({ days = 30 } = {}) {
  const cutoff = getCutoff(days)
  const sql = `
    SELECT e.error_type,
           COUNT(*) AS occurrence_count,
           COUNT(DISTINCT r.pr_number) AS affected_prs
    FROM run_errors e
    JOIN runs r ON r.run_id = e.run_id
    WHERE r.created_at >= ?
    GROUP BY e.error_type
    ORDER BY occurrence_count DESC
  `
  return query(sql, [cutoff])
}

export async function getStageFailures({ days = 30 } = {}) {
  const cutoff = getCutoff(days)
  const sql = `
    SELECT s.stage_name,
           COUNT(*) AS failure_count,
           COUNT(DISTINCT r.pr_number) AS affected_prs
    FROM run_stages s
    JOIN runs r ON r.run_id = s.run_id
    WHERE s.status = 'failed'
      AND r.created_at >= ?
    GROUP BY s.stage_name
    ORDER BY failure_count DESC
  `
  return query(sql, [cutoff])
}

export async function getRerunStats({ days = 30 } = {}) {
  const cutoff = getCutoff(days)
  const sql = `
    SELECT r.pr_number,
           COUNT(*) AS rerun_count,
           SUM(COALESCE(rr.wasted_seconds, r.duration_seconds, 0)) AS wasted_seconds,
           SUM(CASE WHEN rr.rerun_type='same_sha'     THEN 1 ELSE 0 END) AS sha_rerun_count,
           SUM(CASE WHEN rr.rerun_type='merge_commit' THEN 1 ELSE 0 END) AS merge_rerun_count,
           SUM(CASE WHEN rr.rerun_type='same_sha'     THEN 5 ELSE 1 END) AS dev_loss_minutes
    FROM reruns rr
    JOIN runs r ON r.run_id = rr.run_id
    WHERE r.created_at >= ?
    GROUP BY r.pr_number
    ORDER BY rerun_count DESC
  `
  return query(sql, [cutoff])
}

export async function getPrOpenTimes({ days = 30 } = {}) {
  const cutoff = getCutoff(days)
  const sql = `
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
  `
  return query(sql, [cutoff])
}

export async function getScrapeMeta() {
  const sql = `
    SELECT last_scraped_at, run_count, days, pipeline_url, github_repo_url
    FROM scrape_meta
    WHERE key='latest'
  `
  return query(sql, [])
}
