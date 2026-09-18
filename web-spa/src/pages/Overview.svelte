<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { getSummary, getStageFailures, getRerunStats, getPrList, getPrOpenTimes } from '../db.js'
  import { timeWindow, currentPage, stageFilter, selectedPRNumber } from '../stores.js'
  import { Chart, registerables } from 'chart.js'
  Chart.register(...registerables)

  // ── data ────────────────────────────────────────────────────────────────────
  let summary    = null
  let stageData  = []
  let rerunData  = []
  let prData     = []
  let openTimes  = []
  let error      = null
  let loading    = true

  // ── canvas refs ─────────────────────────────────────────────────────────────
  let stageCanvas, rerunTypeCanvas, prTriggersCanvas, prRerunsCanvas, prOpenCanvas
  let stageChart, rerunTypeChart, prTriggersChart, prRerunsChart, prOpenChart

  // ── colour palettes ─────────────────────────────────────────────────────────
  const STAGE_COLORS  = ['#4BC0C0','#FFCE56','#FF6384','#36A2EB','#9966FF','#FF9F40','#C9CBCF']
  const PURPLE        = 'rgba(102,126,234,0.8)'
  const PURPLE_BORDER = 'rgba(102,126,234,1)'
  const PINK          = 'rgba(255,99,132,0.8)'
  const PINK_BORDER   = 'rgba(255,99,132,1)'
  const RED           = 'rgba(252,129,129,0.8)'
  const RED_BORDER    = 'rgba(220,38,38,1)'

  // ── computed helpers ─────────────────────────────────────────────────────────
  $: totalReruns     = rerunData.reduce((s, r) => s + (r.rerun_count || 0), 0)
  $: totalWastedH    = (rerunData.reduce((s, r) => s + (r.wasted_seconds || 0), 0) / 3600).toFixed(1)
  $: totalDevLossMin = rerunData.reduce((s, r) => s + (r.dev_loss_minutes || 0), 0)
  $: totalDevLossH   = (totalDevLossMin / 60).toFixed(1)
  $: subtitleText    = (() => {
    const now = new Date()
    const from = new Date(now - $timeWindow * 86400000)
    const fmt = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    return `Last ${$timeWindow} Days (${fmt(from)} – ${fmt(now)})`
  })()

  // Avg open duration: only PRs that have a valid pr_created_at (skip missing/empty)
  $: avgOpenDurationH = (() => {
    const valid = openTimes.filter(p => p.pr_created_at && p.last_run_at)
    if (!valid.length) return '—'
    const durs = valid.map(p => (new Date(p.last_run_at) - new Date(p.pr_created_at)) / 3600000)
    return (durs.reduce((a, b) => a + b, 0) / durs.length).toFixed(1) + 'h'
  })()

  // Stage name formatter: kebab-case / slug → "Title Case" for display
  function fmtStage(name) {
    if (!name) return name
    return name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }

  // Human-readable stage descriptions for pie chart tooltips
  const STAGE_DESCRIPTIONS = {
    'pr-start':            'Pipeline initialisation — workspace setup, cloning, baseline checks',
    'pr-code-checks':      'Static analysis, linting, secret scanning, CRA compliance checks',
    'pr-code-build':       'Compile, unit tests, image build, artifact signing & scan',
    'pr-deploy-checks':    'Deploy to test environment and run integration / smoke tests',
    'finish':              'DevSecOps finish stage — evaluates compliance gates and sets PR status',
  }
  function stageDesc(rawName) {
    if (!rawName) return ''
    const lower = rawName.toLowerCase()
    for (const [key, desc] of Object.entries(STAGE_DESCRIPTIONS)) {
      if (lower === key || lower.endsWith('-' + key)) return desc
    }
    return fmtStage(rawName) + ' pipeline stage'
  }

  // Navigate to the PRs page and pre-select a PR number
  function goToPR(prNumber) {
    selectedPRNumber.set(Number(prNumber))
    currentPage.set('prs')
  }

  // ── load ─────────────────────────────────────────────────────────────────────
  async function load() {
    loading = true
    error = null
    try {
      const days = $timeWindow
      const [sum, stages, reruns, prs, opens] = await Promise.all([
        getSummary({ days }),
        getStageFailures({ days }),
        getRerunStats({ days }),
        getPrList({ days }),
        getPrOpenTimes({ days }),
      ])
      summary   = sum[0]   || null
      stageData = stages   || []
      rerunData = reruns   || []
      prData    = (prs     || []).slice(0, 20)
      openTimes = (opens   || []).slice(0, 20)
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
      await tick()
      renderCharts()
    }
  }

  // ── charts ───────────────────────────────────────────────────────────────────
  function destroyAll() {
    [stageChart, rerunTypeChart, prTriggersChart, prRerunsChart, prOpenChart]
      .forEach(c => c?.destroy())
  }

  function renderCharts() {
    destroyAll()

    // Stage failure pie
    if (stageData.length && stageCanvas) {
      const total = stageData.reduce((s, d) => s + d.failure_count, 0)
      stageChart = new Chart(stageCanvas, {
        type: 'pie',
        data: {
          labels: stageData.map(s =>
            `${fmtStage(s.stage_name)} (${s.failure_count} builds, ${total ? (s.failure_count/total*100).toFixed(1) : 0}%)`
          ),
          datasets: [{
            data: stageData.map(s => s.failure_count),
            backgroundColor: STAGE_COLORS.slice(0, stageData.length),
            borderWidth: 2, borderColor: '#fff',
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { padding: 15, font: { size: 12 }, color: '#333' } },
            tooltip: { callbacks: {
              label: ctx => {
                const t = ctx.dataset.data.reduce((a, b) => a + b, 0)
                const pct = t > 0 ? (ctx.parsed / t * 100).toFixed(1) : 0
                return `${ctx.label.split(' (')[0]}: ${ctx.parsed} builds (${pct}%)`
              },
              afterLabel: ctx => stageDesc(stageData[ctx.dataIndex]?.stage_name)
            }}
          },
          onClick: (_, elements) => {
            if (elements.length) {
              stageFilter.set(stageData[elements[0].index].stage_name)
              currentPage.set('stages')
            }
          }
        }
      })
    }

    // Rerun type pie (sha vs merge)
    const shaReruns   = rerunData.reduce((s, r) => s + (r.sha_rerun_count   || 0), 0)
    const mergeReruns = rerunData.reduce((s, r) => s + (r.merge_rerun_count || 0), 0)
    // fall back to total if per-type not returned
    const totalR = shaReruns + mergeReruns || totalReruns
    if (totalR > 0 && rerunTypeCanvas) {
      const sa = shaReruns || 0, me = mergeReruns || totalReruns
      const tot = sa + me || 1
      rerunTypeChart = new Chart(rerunTypeCanvas, {
        type: 'pie',
        data: {
          labels: [
            `Manual Reruns (Same SHA) - ${sa} (${(sa/tot*100).toFixed(1)}%)`,
            `Merge Commit Reruns (Auto) - ${me} (${(me/tot*100).toFixed(1)}%)`,
          ],
          datasets: [{
            data: [sa, me],
            backgroundColor: ['rgba(220,38,38,0.8)', 'rgba(251,146,60,0.8)'],
            borderWidth: 2, borderColor: '#fff',
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'right', labels: { padding: 15, font: { size: 12 }, color: '#333' } },
            tooltip: { callbacks: {
              label: ctx => ctx.label.split(' - ')[0] + ': ' + ctx.parsed + ' reruns'
            }}
          }
        }
      })
    }

    // PR triggers bar
    if (prData.length && prTriggersCanvas) {
      prTriggersChart = new Chart(prTriggersCanvas, {
        type: 'bar',
        data: {
          labels: prData.map(p => `#${p.pr_number}`),
          datasets: [{ label: 'Number of Triggers', data: prData.map(p => p.total_runs),
            backgroundColor: PURPLE, borderColor: PURPLE_BORDER, borderWidth: 1 }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => 'Triggers: ' + ctx.parsed.x } }
          },
          scales: {
            x: { beginAtZero: true,
              title: { display: true, text: 'Number of Pipeline Triggers', color: '#666' },
              ticks: { color: '#666' }, grid: { color: 'rgba(0,0,0,0.05)' } },
            y: { ticks: { color: '#666', cursor: 'pointer' }, grid: { color: 'rgba(0,0,0,0.05)' } },
          },
          onClick: (_, elements) => {
            if (elements.length) goToPR(prData[elements[0].index].pr_number)
          }
        }
      })
    }

    // PR reruns bar (without code changes)
    const rerunSorted = [...rerunData].sort((a, b) => b.rerun_count - a.rerun_count).slice(0, 20)
    if (rerunSorted.length && prRerunsCanvas) {
      prRerunsChart = new Chart(prRerunsCanvas, {
        type: 'bar',
        data: {
          labels: rerunSorted.map(r => `#${r.pr_number}`),
          datasets: [{ label: 'Number of Reruns', data: rerunSorted.map(r => r.rerun_count),
            backgroundColor: RED, borderColor: RED_BORDER, borderWidth: 2 }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: {
              label: ctx => 'Reruns: ' + ctx.parsed.x,
              afterLabel: () => 'Indicates flaky tests or infrastructure issues'
            }}
          },
          scales: {
            x: { beginAtZero: true,
              title: { display: true, text: 'Number of Reruns Without Code Changes', color: '#666' },
              ticks: { color: '#666', stepSize: 1 }, grid: { color: 'rgba(0,0,0,0.05)' } },
            y: { ticks: { color: '#666', cursor: 'pointer' }, grid: { color: 'rgba(0,0,0,0.05)' } },
          },
          onClick: (_, elements) => {
            if (elements.length) goToPR(rerunSorted[elements[0].index].pr_number)
          }
        }
      })
    }

    // PR open duration bar
    if (openTimes.length && prOpenCanvas) {
      const openSorted = [...openTimes].sort((a, b) => {
        const durA = a.last_run_at && a.pr_created_at
          ? (new Date(a.last_run_at) - new Date(a.pr_created_at)) / 3600000 : 0
        const durB = b.last_run_at && b.pr_created_at
          ? (new Date(b.last_run_at) - new Date(b.pr_created_at)) / 3600000 : 0
        return durB - durA
      }).slice(0, 20)
      prOpenChart = new Chart(prOpenCanvas, {
        type: 'bar',
        data: {
          labels: openSorted.map(p => `#${p.pr_number}`),
          datasets: [{ label: 'Open Duration (hours)',
            data: openSorted.map(p => {
              if (!p.last_run_at || !p.pr_created_at) return 0
              return ((new Date(p.last_run_at) - new Date(p.pr_created_at)) / 3600000).toFixed(1)
            }),
            backgroundColor: PINK, borderColor: PINK_BORDER, borderWidth: 1 }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: {
              label: ctx => {
                const h = ctx.parsed.x
                return `Open: ${Math.floor(h/24)}d ${Math.floor(h%24)}h`
              }
            }}
          },
          scales: {
            x: { beginAtZero: true,
              title: { display: true, text: 'Duration (hours)', color: '#666' },
              ticks: { color: '#666' }, grid: { color: 'rgba(0,0,0,0.05)' } },
            y: { ticks: { color: '#666', cursor: 'pointer' }, grid: { color: 'rgba(0,0,0,0.05)' } },
          },
          onClick: (_, elements) => {
            if (elements.length) goToPR(openSorted[elements[0].index].pr_number)
          }
        }
      })
    }
  }

  const unsub = timeWindow.subscribe(() => load())
  onMount(load)
  onDestroy(() => { unsub(); destroyAll() })
</script>

<!-- ── Page shell ──────────────────────────────────────────────────────────── -->
<div class="page">

  {#if loading}
    <div class="loading-wrap"><p class="loading-text">Loading…</p></div>

  {:else if error}
    <div class="error-wrap"><p class="error-text">⚠ {error}</p></div>

  {:else}

    <!-- Title -->
    <h1>🔍 Pipeline Developer Productivity Loss Dashboard</h1>
    <p class="subtitle">{subtitleText}</p>

    <!-- Metric cards -->
    <div class="metrics-grid">
      <div class="metric-card" role="button" tabindex="0" on:click={() => currentPage.set('prs')}>
        <div class="metric-value">{summary?.total_prs ?? '—'}</div>
        <div class="metric-label">Total PRs</div>
        <div class="metric-sublabel">{summary ? (summary.total_runs ?? 0) + ' total pipeline runs' : ''}</div>
      </div>

      <div class="metric-card" role="button" tabindex="0" on:click={() => currentPage.set('errors')}>
        <div class="metric-value">{summary ? Number(summary.failure_rate_pct).toFixed(1) + '%' : '—'}</div>
        <div class="metric-label">Build Failure Rate</div>
        <div class="metric-sublabel">{summary ? (summary.failed_runs ?? 0) + ' of ' + (summary.total_runs ?? 0) + ' builds failed' : ''}</div>
      </div>

      <div class="metric-card" role="button" tabindex="0" on:click={() => currentPage.set('prs')}>
        <div class="metric-value">{avgOpenDurationH}</div>
        <div class="metric-label">Avg Open Duration</div>
        <div class="metric-sublabel">Average time PRs stay open</div>
      </div>

      <div class="metric-card" role="button" tabindex="0" on:click={() => currentPage.set('reruns')}>
        <div class="metric-value">{totalWastedH}h</div>
        <div class="metric-label">Total Loss in Compute</div>
        <div class="metric-sublabel">Wasted on {totalReruns} reruns</div>
      </div>

      <div class="metric-card" role="button" tabindex="0" on:click={() => currentPage.set('reruns')}>
        <div class="metric-value">{totalDevLossH}h</div>
        <div class="metric-label">Total Loss in Dev Productivity</div>
        <div class="metric-sublabel">Manual: 5 min, Merge: 1 min</div>
      </div>
    </div>

    <!-- Stage failure pie -->
    <div class="chart-container">
      <h2 class="chart-title">🎯 Stage Failure Distribution</h2>
      <p class="chart-desc">Shows the number of builds that failed at each pipeline stage</p>
      {#if stageData.length === 0}
        <p class="empty">No stage data yet — run the scraper first.</p>
      {:else}
        <div class="chart-wrapper"><canvas bind:this={stageCanvas}></canvas></div>
      {/if}
    </div>

    <!-- Rerun type pie -->
    <div class="chart-container">
      <h2 class="chart-title">🔄 Rerun Type Distribution</h2>
      <p class="chart-desc">Manual reruns (same SHA) vs automatic merge commit reruns — both waste compute and interrupt developers</p>
      {#if totalReruns === 0}
        <p class="empty">No rerun data yet.</p>
      {:else}
        <div class="chart-wrapper"><canvas bind:this={rerunTypeCanvas}></canvas></div>
      {/if}
    </div>

    <!-- Two-column: PR triggers + PR reruns -->
    <div class="two-column">
      <div class="chart-container">
        <h2 class="chart-title">🔄 Top 20 PRs by Total Trigger Count</h2>
        {#if prData.length === 0}
          <p class="empty">No PR data yet.</p>
        {:else}
          <div class="chart-wrapper"><canvas bind:this={prTriggersCanvas}></canvas></div>
        {/if}
      </div>

      <div class="chart-container">
        <h2 class="chart-title">🔄 Top 20 PRs by Rerun Count (Without Code Changes)</h2>
        <p class="chart-desc">Reruns indicate flaky tests or infrastructure issues — key productivity loss metric</p>
        {#if rerunData.length === 0}
          <p class="empty">No rerun data yet.</p>
        {:else}
          <div class="chart-wrapper"><canvas bind:this={prRerunsCanvas}></canvas></div>
        {/if}
      </div>
    </div>

    <!-- PR open duration bar -->
    <div class="chart-container">
      <h2 class="chart-title">⏱️ Top 20 PRs by Open Duration</h2>
      {#if openTimes.length === 0}
        <p class="empty">No open-time data yet.</p>
      {:else}
        <div class="chart-wrapper"><canvas bind:this={prOpenCanvas}></canvas></div>
      {/if}
    </div>

  {/if}
</div>

<style>
  /* ── page shell ─────────────────────────────────────────────────────────── */
  :global(body) {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    min-height: 100vh;
  }

  .page {
    max-width: 1400px;
    margin: 0 auto;
    padding: 10px 0 40px;
    display: flex;
    flex-direction: column;
    gap: 0; /* controlled per-section below */
  }

  /* ── header ─────────────────────────────────────────────────────────────── */
  h1 {
    color: white;
    text-align: center;
    font-size: 2rem;
    font-weight: 700;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    margin-bottom: 6px;
  }

  .subtitle {
    color: rgba(255,255,255,0.9);
    text-align: center;
    font-size: 1rem;
    margin-bottom: 24px;
  }

  /* ── metric cards ───────────────────────────────────────────────────────── */
  .metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }

  .metric-card {
    background: white;
    border-radius: 12px;
    padding: 22px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    transition: transform 0.2s ease;
    cursor: pointer;
  }
  .metric-card:hover { transform: translateY(-4px); }

  .metric-value {
    font-size: 2.2em;
    font-weight: 700;
    color: #667eea;
    margin-bottom: 4px;
  }

  .metric-label {
    color: #444;
    font-size: 0.82em;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 600;
  }

  .metric-sublabel {
    color: #999;
    font-size: 0.8em;
    margin-top: 4px;
  }

  /* ── chart containers ───────────────────────────────────────────────────── */
  .chart-container {
    background: white;
    border-radius: 12px;
    padding: 28px;
    margin-bottom: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
  }

  .chart-title {
    font-size: 1.25rem;
    color: #222;
    font-weight: 600;
    margin-bottom: 8px;
  }

  .chart-desc {
    color: #666;
    font-size: 0.88em;
    margin-bottom: 16px;
  }

  .chart-wrapper {
    position: relative;
    height: 380px;
  }

  /* ── two-column row ─────────────────────────────────────────────────────── */
  .two-column {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 0; /* chart-container inside already has margin-bottom */
  }

  @media (max-width: 900px) {
    .two-column { grid-template-columns: 1fr; }
  }

  /* ── states ─────────────────────────────────────────────────────────────── */
  .loading-wrap, .error-wrap {
    display: flex; align-items: center; justify-content: center; height: 60vh;
  }
  .loading-text { color: rgba(255,255,255,0.8); font-size: 1.2rem; }
  .error-text   { color: #fee2e2; background: rgba(0,0,0,0.3); padding: 1rem 2rem; border-radius: 8px; }
  .empty        { color: #aaa; font-size: 0.85rem; padding: 1rem 0; }
</style>
