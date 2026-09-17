<script>
  import { onMount, onDestroy, tick } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { timeWindow, stageFilter } from '../stores.js'
  import { Chart, registerables } from 'chart.js'
  Chart.register(...registerables)

  let stageData = []
  let loading = false
  let error = null
  let pieCanvas
  let pieChart
  let activeFilter = null

  const COLORS = ['#38bdf8','#f472b6','#4ade80','#fb923c','#a78bfa','#facc15','#34d399','#f87171']

  async function load() {
    loading = true; error = null
    try {
      stageData = await invoke('get_stage_failures', { days: $timeWindow }) || []
    } catch (e) {
      error = String(e)
    } finally {
      loading = false
      await tick()
      renderChart()
    }
  }

  function renderChart() {
    pieChart?.destroy()
    if (!stageData.length || !pieCanvas) return
    pieChart = new Chart(pieCanvas, {
      type: 'pie',
      data: {
        labels: stageData.map(s => s.stage_name),
        datasets: [{ data: stageData.map(s => s.failure_count), backgroundColor: COLORS }]
      },
      options: {
        plugins: { legend: { labels: { color: '#e2e8f0' } } },
        onClick: (_, elements) => {
          if (elements.length) {
            activeFilter = stageData[elements[0].index].stage_name
            stageFilter.set(activeFilter)
          }
        }
      }
    })
  }

  const unsubFilter = stageFilter.subscribe(f => activeFilter = f)
  const unsub = timeWindow.subscribe(() => load())
  onMount(load)
  onDestroy(() => { unsub(); unsubFilter(); pieChart?.destroy() })

  $: filtered = activeFilter ? stageData.filter(s => s.stage_name === activeFilter) : stageData
</script>

<div class="page">
  <h1>Stage Failures</h1>
  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else}
    <div class="top">
      <div class="chart-box">
        <h3>Stage Failure Distribution</h3>
        {#if stageData.length === 0}
          <p class="empty">No stage data yet — run the scraper first.</p>
        {:else}
          <canvas bind:this={pieCanvas}></canvas>
        {/if}
      </div>
      <div class="table-box">
        {#if activeFilter}
          <div class="filter-badge">
            Filter: <b>{activeFilter}</b>
            <button on:click={() => { activeFilter = null; stageFilter.set(null) }}>✕</button>
          </div>
        {/if}
        <table>
          <thead><tr><th>Stage</th><th>Failures</th><th>PRs Affected</th></tr></thead>
          <tbody>
            {#each filtered as s}
              <tr>
                <td>{s.stage_name}</td>
                <td>{s.failure_count}</td>
                <td>{s.affected_prs}</td>
              </tr>
            {/each}
            {#if filtered.length === 0}
              <tr><td colspan="3" style="color:#475569; text-align:center; padding:1rem">No stage data yet.</td></tr>
            {/if}
          </tbody>
        </table>
      </div>
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

  .top { display: flex; gap: 1rem; flex-wrap: wrap; }
  .chart-box { flex: 1; min-width: 280px; max-width: 400px; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; }
  .table-box { flex: 2; min-width: 300px; background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1rem; overflow-x: auto; }

  .filter-badge {
    display: inline-flex; align-items: center; gap: 0.5rem;
    background: #0c4a6e; padding: 0.3rem 0.7rem; border-radius: 20px;
    font-size: 0.8rem; margin-bottom: 0.8rem;
  }
  .filter-badge button { background: none; border: none; color: #f87171; cursor: pointer; font-size: 1rem; }

  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { color: #64748b; text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #334155; }
  td { padding: 0.4rem 0.6rem; border-bottom: 1px solid #1e293b; }
  tr:hover td { background: #334155; }
</style>
