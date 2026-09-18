<script>
  import { onMount, onDestroy } from 'svelte'
  import { getPrList, getRunDistribution } from '../db.js'
  import { timeWindow, selectedPRNumber } from '../stores.js'
  import { Chart, registerables } from 'chart.js'
  Chart.register(...registerables)

  let prList = []
  let selectedPR = null
  let runDist = []
  let loading = false
  let detailLoading = false
  let error = null

  let scatterCanvas, histCanvas
  let scatterChart, histChart

  const COLORS = { succeeded: '#4ade80', failed: '#f87171', cancelled: '#fb923c' }

  async function load() {
    loading = true
    error = null
    try {
      prList = await getPrList({ days: $timeWindow }) || []
      // Auto-select a PR if one was set via the Overview charts
      const jumpTo = $selectedPRNumber
      if (jumpTo) {
        selectedPRNumber.set(null)
        const target = prList.find(p => p.pr_number === jumpTo)
        if (target) selectPR(target)
      }
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
    }
  }

  async function selectPR(pr) {
    selectedPR = pr
    detailLoading = true
    try {
      runDist = await getRunDistribution({ prNumber: pr.pr_number }) || []
    } catch (e) {
      error = String(e)
    } finally {
      detailLoading = false
      renderDetail()
    }
  }

  function renderDetail() {
    scatterChart?.destroy(); histChart?.destroy()
    if (!runDist.length) return

    const points = runDist.map(r => ({
      x: new Date(r.created_at).getTime(),
      y: r.duration_seconds / 60,
      status: r.status,
      build: r.build_number,
    }))

    if (scatterCanvas) {
      scatterChart = new Chart(scatterCanvas, {
        type: 'scatter',
        data: {
          datasets: [{
            label: 'Runs',
            data: points,
            backgroundColor: points.map(p => COLORS[p.status] || '#94a3b8'),
            pointRadius: 6,
          }]
        },
        options: {
          scales: {
            x: { type: 'linear', ticks: { color: '#94a3b8', callback: v => new Date(v).toLocaleDateString() }, grid: { color: '#1e293b' } },
            y: { title: { display: true, text: 'Duration (min)', color: '#94a3b8' }, ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
          },
          plugins: { legend: { display: false } }
        }
      })
    }

    // Histogram of durations
    const allDurs = runDist.map(r => r.duration_seconds / 60)
    const failDurs = runDist.filter(r => r.status === 'failed').map(r => r.duration_seconds / 60)
    const bins = 10
    const maxD = Math.max(...allDurs, 1)
    const step = maxD / bins
    const labels = Array.from({ length: bins }, (_, i) => `${(i * step).toFixed(0)}-${((i + 1) * step).toFixed(0)}m`)
    const hist = (durs) => labels.map((_, i) => durs.filter(d => d >= i * step && d < (i + 1) * step).length)

    if (histCanvas) {
      histChart = new Chart(histCanvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'All runs', data: hist(allDurs), backgroundColor: '#38bdf8' },
            { label: 'Failed', data: hist(failDurs), backgroundColor: '#f87171' },
          ]
        },
        options: {
          scales: {
            x: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
            y: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
          },
          plugins: { legend: { labels: { color: '#e2e8f0' } } }
        }
      })
    }
  }

  const unsub = timeWindow.subscribe(() => load())
  onMount(load)
  onDestroy(() => { unsub(); scatterChart?.destroy(); histChart?.destroy() })
</script>

<div class="page">
  <h1>PR Detail</h1>
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else}
    <div class="layout">
      <!-- PR list -->
      <div class="pr-list">
        <h3>PRs ({prList.length})</h3>
        {#each prList as pr}
          <div
            class="pr-row"
            class:active={selectedPR?.pr_number === pr.pr_number}
            on:click={() => selectPR(pr)}
            role="button" tabindex="0"
          >
            <span class="pr-num">#{pr.pr_number}</span>
            <span class="pr-runs">{pr.total_runs} runs</span>
            <span class="pr-author">{pr.author}</span>
          </div>
        {/each}
      </div>

      <!-- Detail panel -->
      {#if selectedPR}
        <div class="detail">
          <h2>PR #{selectedPR.pr_number}</h2>
          <p class="pr-title">{selectedPR.title}</p>
          {#if detailLoading}
            <p class="muted">Loading runs…</p>
          {:else}
            <div class="chart-box">
              <h3>Run Timeline (duration vs time)</h3>
              <canvas bind:this={scatterCanvas} height="200"></canvas>
            </div>
            <div class="chart-box">
              <h3>Duration Distribution</h3>
              <canvas bind:this={histCanvas} height="160"></canvas>
            </div>
            <div class="rerun-badges">
              {#each runDist as r}
                <span class="badge badge-{r.status}">
                  #{r.build_number} · {r.status} · {(r.duration_seconds/60).toFixed(0)}m
                </span>
              {/each}
            </div>
          {/if}
        </div>
      {:else}
        <div class="detail empty"><p class="muted">← Select a PR to see run details</p></div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 1rem; }
  h1 { font-size: 1.4rem; font-weight: 700; color: #38bdf8; }
  h2 { font-size: 1.1rem; font-weight: 600; }
  h3 { font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.4rem; }
  .muted { color: #64748b; }
  .err { color: #f87171; }
  .pr-title { font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.8rem; }

  .layout { display: flex; gap: 1rem; align-items: flex-start; }

  .pr-list {
    width: 280px; flex-shrink: 0;
    background: #1e293b; border: 1px solid #334155; border-radius: 10px;
    padding: 0.8rem; max-height: 70vh; overflow-y: auto;
  }
  .pr-list h3 { margin-bottom: 0.6rem; }
  .pr-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.5rem 0.6rem; border-radius: 6px; cursor: pointer;
    font-size: 0.85rem; gap: 0.4rem; transition: background 0.1s;
  }
  .pr-row:hover { background: #334155; }
  .pr-row.active { background: #0c4a6e; }
  .pr-num { font-weight: 600; color: #38bdf8; }
  .pr-runs { color: #94a3b8; font-size: 0.78rem; }
  .pr-author { color: #64748b; font-size: 0.78rem; }

  .detail {
    flex: 1; background: #1e293b; border: 1px solid #334155;
    border-radius: 10px; padding: 1rem; display: flex; flex-direction: column; gap: 0.8rem;
  }
  .detail.empty { justify-content: center; align-items: center; height: 200px; }

  .chart-box { background: #0f172a; border-radius: 8px; padding: 0.8rem; }

  .rerun-badges { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .badge { font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; }
  .badge-succeeded { background: #14532d; color: #4ade80; }
  .badge-failed    { background: #450a0a; color: #f87171; }
  .badge-cancelled { background: #431407; color: #fb923c; }
</style>
