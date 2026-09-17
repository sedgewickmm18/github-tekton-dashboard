<script>
  import { onMount, onDestroy } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { timeWindow } from '../stores.js'
  import { Chart, registerables } from 'chart.js'
  Chart.register(...registerables)

  let rerunData = []
  let loading = false
  let error = null
  let barCanvas
  let barChart

  let totalCompute = 0  // seconds
  let totalDevLoss  = 0  // minutes

  async function load() {
    loading = true; error = null
    try {
      rerunData = await invoke('get_rerun_stats', { days: $timeWindow }) || []
      totalCompute = rerunData.reduce((s, r) => s + (r.wasted_seconds || 0), 0)
      totalDevLoss  = rerunData.reduce((s, r) => s + (r.dev_loss_minutes || 0), 0)
    } catch (e) { error = String(e) }
    finally { loading = false; renderChart() }
  }

  function renderChart() {
    barChart?.destroy()
    if (!rerunData.length || !barCanvas) return
    const top = [...rerunData].sort((a, b) => b.rerun_count - a.rerun_count).slice(0, 20)
    barChart = new Chart(barCanvas, {
      type: 'bar',
      data: {
        labels: top.map(r => `#${r.pr_number}`),
        datasets: [{ label: 'Reruns', data: top.map(r => r.rerun_count), backgroundColor: '#f87171' }]
      },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
        }
      }
    })
  }

  function fmtDuration(secs) {
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  const unsub = timeWindow.subscribe(() => load())
  onMount(load)
  onDestroy(() => { unsub(); barChart?.destroy() })
</script>

<div class="page">
  <h1>Reruns &amp; Productivity Loss</h1>
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else}
    <div class="tiles">
      <div class="tile">
        <span class="tile-label">Total Compute Loss</span>
        <span class="tile-value">{fmtDuration(totalCompute)}</span>
      </div>
      <div class="tile">
        <span class="tile-label">Dev Productivity Loss</span>
        <span class="tile-value">{totalDevLoss} min</span>
        <span class="tile-sub">@ 5 min/rerun context switch</span>
      </div>
    </div>

    <div class="chart-box">
      <h3>Top 20 PRs by Rerun Count</h3>
      <canvas bind:this={barCanvas} height="260"></canvas>
    </div>

    <div class="table-box">
      <h3>Per-PR Rerun Detail</h3>
      <table>
        <thead><tr><th>PR</th><th>Reruns</th><th>Compute Lost</th><th>Dev Lost (min)</th></tr></thead>
        <tbody>
          {#each rerunData as r}
            <tr>
              <td>#{r.pr_number}</td>
              <td>{r.rerun_count}</td>
              <td>{fmtDuration(r.wasted_seconds)}</td>
              <td>{r.dev_loss_minutes}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 1.5rem; }
  h1 { font-size: 1.4rem; font-weight: 700; color: #38bdf8; }
  h3 { font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.5rem; }
  .muted { color: #64748b; }
  .err { color: #f87171; }

  .tiles { display: flex; gap: 1rem; flex-wrap: wrap; }
  .tile {
    flex: 1; min-width: 200px;
    background: #1e293b; border: 1px solid #334155; border-radius: 10px;
    padding: 1rem; display: flex; flex-direction: column; gap: 0.25rem;
  }
  .tile-label { font-size: 0.78rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
  .tile-value { font-size: 2rem; font-weight: 700; color: #f87171; }
  .tile-sub   { font-size: 0.72rem; color: #475569; }

  .chart-box, .table-box {
    background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem;
  }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { color: #64748b; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #334155; }
  td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #334155; }
</style>
