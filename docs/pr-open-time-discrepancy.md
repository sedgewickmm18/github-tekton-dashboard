# PR Open Time Discrepancy: 229h vs 132h

## Overview

The repository dashboard reports an average PR open duration of **229h**, while the skill
script `~/.bob/skills/generic-pipeline-developer-productivity-loss/calculate-pr-open-time.py`
reports **132h** for the same pipeline data. Both scripts compute the same quantity —
`last_run_at − pr_created_at` per PR, then average — but they draw `last_run_at` from
different populations of runs.

---

## How Each Side Computes the Duration

### Skill (`calculate-pr-open-time.py`)

```
pr_created_at  ←  pull_request.created_at  inside the first run's event_params_blob
last_run_at    ←  MAX(run.created_at)  across ALL runs in pr-builds-analyzed.json
```

No time-window filter is applied. The JSON file contains every run ever fetched; the
maximum is the true all-time last run for each PR.

### Repository (`sqlite_backend.py` / `sqlite.rs` → `get_pr_open_times`)

```sql
SELECT r.pr_number,
       p.created_at         AS pr_created_at,   -- from prs table (real GitHub date)
       MAX(r.created_at)    AS last_run_at,      -- from runs table, filtered by window
       ...
FROM runs r
LEFT JOIN prs p ON p.pr_number = r.pr_number
WHERE r.created_at >= ?                          -- ← time-window cutoff (e.g. 30 days)
GROUP BY r.pr_number
```

`p.created_at` is the real GitHub PR creation date stored at scrape time (potentially
months in the past). `MAX(r.created_at)` is the most recent run **within the selected
window**.

---

## Root Cause

The two endpoints are not symmetric with respect to time:

| Endpoint | Scope |
|---|---|
| `pr_created_at` | Real PR creation date — **unbounded** (may be months ago) |
| `last_run_at` | Most recent run — **clamped to the time window** |

For a PR that was opened long before the window but has activity inside it, the repo
measures a span from a distant past anchor all the way to the recent window edge.
The skill, working from an unfiltered JSON snapshot, uses a `last_run_at` that may be
any all-time value — often an earlier date that produces a shorter span.

### Concrete example

Suppose a PR was opened 90 days ago and has runs spread across all 90 days, with the
most recent run 5 days ago:

| | `pr_created_at` | `last_run_at` | Duration |
|---|---|---|---|
| **Skill** | 90 days ago | 5 days ago (true last run) | **85 days** |
| **Repo (30-day window)** | 90 days ago | 5 days ago (within window) | **85 days** |

Same result here. Now suppose the most recent run was 35 days ago (just outside a
30-day window):

| | `pr_created_at` | `last_run_at` | Duration |
|---|---|---|---|
| **Skill** | 90 days ago | 35 days ago | **55 days** |
| **Repo (30-day window)** | — | — | **PR excluded** (no runs in window) |

The PR disappears from the repo's average. The remaining PRs in the repo's result set
are those with recent runs, and for long-lived PRs their `pr_created_at` (old) vs
`last_run_at` (near the window boundary) creates consistently large spans.

---

## Affected Code

| File | Location | Issue |
|---|---|---|
| [`scraper/src/tekton_scraper/db/sqlite_backend.py`](../scraper/src/tekton_scraper/db/sqlite_backend.py) | `query_pr_open_times`, line 356 | SQL uses `WHERE r.created_at >= ?` on runs but joins `prs.created_at` unfiltered |
| [`dashboard/src-tauri/src/sqlite.rs`](../dashboard/src-tauri/src/sqlite.rs) | `get_pr_open_times`, line 197 | Same query duplicated in the Rust Tauri backend |
| [`dashboard/src/pages/Overview.svelte`](../dashboard/src/pages/Overview.svelte) | `avgOpenDurationH`, line 43 | Frontend re-derives the duration from the returned timestamps — correct, but inherits the skew |

---

## Fix Options

### Option A — Remove the time-window filter from the open-time query (recommended)

Do not filter by `r.created_at >= ?` in `get_pr_open_times`. Instead, include all PRs
that have any run at all and compute `last_run_at` from the full runs table. Apply a
separate filter only on which PRs to include (e.g. PRs with at least one run in the
window).

```sql
-- Include only PRs active in the window, but measure last_run across all time
SELECT r.pr_number,
       p.created_at      AS pr_created_at,
       MAX(r.created_at) AS last_run_at,
       p.author,
       COUNT(*) AS total_runs
FROM runs r
LEFT JOIN prs p ON p.pr_number = r.pr_number
WHERE r.pr_number IN (
    SELECT DISTINCT pr_number FROM runs WHERE created_at >= ?
)
GROUP BY r.pr_number
ORDER BY r.pr_number
```

### Option B — Align with the skill: derive `pr_created_at` from runs, not the prs table

Store and use the event-params PR creation date only from the runs table itself,
keeping both timestamps in the same scope.

### Option C — Document the intentional difference

If the 30-day window scoping is intentional (i.e. "how long have PRs with recent
activity been open"), add a comment and update the metric label in the dashboard to
reflect that it measures "open duration for PRs active in the last N days".

---

## Both Sides Use the Wrong End Point

Even after fixing the time-window asymmetry, both implementations share a deeper
conceptual flaw: they use `last_run_at` (the timestamp of the last pipeline run) as a
proxy for when the PR stopped being open. This is not the same thing:

- A PR can be open for days with no pipeline activity → open time is **under**-counted.
- A PR can be closed immediately after its last run → the proxy accidentally gets it
  right, but only by coincidence.
- A PR merged weeks ago with a recent automated re-run looks "still open" →
  open time is **over**-counted.

### What should be measured

The correct quantity is:

```
closed_at (or merged_at)  −  pr_created_at    # for already-closed PRs
now                        −  pr_created_at    # for PRs still open
```

Both `closed_at` and `merged_at` are present in the GitHub `pull_request` object
carried inside each run's `event_params_blob`, and can also be fetched directly from
the GitHub API. Neither side currently reads those fields at all.

### Flaws summarised

| | Skill | Repo |
|---|---|---|
| `pr_created_at` | ✅ correct (from event params) | ✅ correct (stored in `prs` table) |
| `last_run_at` used as end point | ❌ wrong concept | ❌ wrong concept |
| Time-window applied to end point | ✅ none | ❌ yes — inflates durations |
| Correct end point (`closed_at` / `merged_at`) | ❌ not used | ❌ not used |

---

## Conclusion

The 97-hour difference is not an arithmetic error — both sides compute
`last_run_at − pr_created_at` correctly given their inputs. The gap arises from a
**population difference**: the repo clamps `last_run_at` to the selected time window
while leaving `pr_created_at` unbounded, consistently pairing an old start anchor with
a recent endpoint for long-lived PRs.

More fundamentally, **both sides measure the wrong thing**. PR open time should be
computed from `pull_request.closed_at` (or `merged_at`) as the end point, not from the
timestamp of the last pipeline run. Using `last_run_at` is a proxy that under-counts
quiet PRs, over-counts PRs that receive late automated runs after closure, and produces
results that vary with the chosen time window rather than reflecting actual review
duration.
