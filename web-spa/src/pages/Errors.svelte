<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { getErrorBreakdown } from '../db.js'
  import { timeWindow } from '../stores.js'
  import { Chart, registerables } from 'chart.js'
  Chart.register(...registerables)

  let errorData = []
  let loading = false
  let error = null
  let barCanvas
  let barChart

  const COLORS = ['#38bdf8','#f472b6','#4ade80','#fb923c','#a78bfa','#facc15','#34d399','#f87171']

  async function load() {
    loading = true; error = null
    try {
      errorData = await getErrorBreakdown({ days: $timeWindow }) || []
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
      await tick()
      renderChart()
    }
  }

  function renderChart() {
    barChart?.destroy()
    if (!errorData.length || !barCanvas) return
    const total = errorData.reduce((s, e) => s + e.occurrence_count, 0) || 1
    barChart = new Chart(barCanvas, {
      type: 'bar',
      data: {
        labels: errorData.map(e => e.error_type),
        datasets: [{
          label: '% of builds affected',
          data: errorData.map(e => (e.occurrence_count / total * 100).toFixed(1)),
          backgroundColor: COLORS,
        }]
      },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#94a3b8', callback: v => v + '%' }, grid: { color: '#1e293b' } },
          y: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
        }
      }
    })
  }

  const unsub = timeWindow.subscribe(() => load())
  onMount(load)
  onDestroy(() => { unsub(); barChart?.destroy() })
</script>

<div class="page">
  <h1>Error Analysis</h1>
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else}
    <div class="chart-box">
      <h3>Error Type — % of Builds Affected</h3>
      {#if errorData.length === 0}
        <p class="empty">No error data yet — run the scraper with local logs.</p>
      {:else}
        <canvas bind:this={barCanvas} height="220"></canvas>
      {/if}
    </div>

    <div class="grid">
      {#each errorData as e, i}
        <div class="card" style="border-color: {COLORS[i % COLORS.length]}">
          <span class="count">{e.occurrence_count}</span>
          <span class="name">{e.error_type}</span>
          <span class="prs">{e.affected_prs} PRs affected</span>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 1.5rem; }
  h1 { font-size: 1.4rem; font-weight: 700; color: #38bdf8; }
  h3 { font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.5rem; }
  .muted { color: #64748b; }
  .err { color: #f87171; }
  .empty { color: #475569; font-size: 0.82rem; padding: 1rem 0; }
  .chart-box { background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; }
  .grid { display: flex; flex-wrap: wrap; gap: 1rem; }
  .card {
    flex: 1; min-width: 160px;
    background: #1e293b; border: 2px solid; border-radius: 10px;
    padding: 1rem; display: flex; flex-direction: column; gap: 0.25rem;
  }
  .count { font-size: 2rem; font-weight: 700; }
  .name  { font-size: 0.85rem; color: #e2e8f0; }
  .prs   { font-size: 0.78rem; color: #64748b; }
</style>
