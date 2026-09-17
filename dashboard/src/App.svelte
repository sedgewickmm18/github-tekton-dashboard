<script>
  import { timeWindow, currentPage } from './stores.js'
  import Overview  from './pages/Overview.svelte'
  import PRDetail  from './pages/PRDetail.svelte'
  import Errors    from './pages/Errors.svelte'
  import Stages    from './pages/Stages.svelte'
  import Reruns    from './pages/Reruns.svelte'
  import Settings  from './pages/Settings.svelte'

  const pages = [
    { id: 'overview', label: '📊 Overview' },
    { id: 'prs',      label: '🔀 PRs' },
    { id: 'errors',   label: '❌ Errors' },
    { id: 'stages',   label: '📋 Stages' },
    { id: 'reruns',   label: '🔄 Reruns' },
    { id: 'settings', label: '⚙️ Settings' },
  ]

  const windows = [
    { value: 7,   label: '7 days' },
    { value: 30,  label: '30 days' },
    { value: 90,  label: '90 days' },
  ]
</script>

<div class="shell">
  <!-- Top navigation bar -->
  <nav class="topbar">
    <span class="brand">🚀 Tekton Dashboard</span>

    <div class="nav-links">
      {#each pages as p}
        <button
          class:active={$currentPage === p.id}
          on:click={() => currentPage.set(p.id)}
        >{p.label}</button>
      {/each}
    </div>

    <div class="time-selector">
      {#each windows as w}
        <button
          class:selected={$timeWindow === w.value}
          on:click={() => timeWindow.set(w.value)}
        >{w.label}</button>
      {/each}
    </div>
  </nav>

  <!-- Page content -->
  <main class="content">
    {#if $currentPage === 'overview'}
      <Overview />
    {:else if $currentPage === 'prs'}
      <PRDetail />
    {:else if $currentPage === 'errors'}
      <Errors />
    {:else if $currentPage === 'stages'}
      <Stages />
    {:else if $currentPage === 'reruns'}
      <Reruns />
    {:else if $currentPage === 'settings'}
      <Settings />
    {/if}
  </main>
</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    min-height: 100vh;
  }

  .shell { display: flex; flex-direction: column; height: 100vh; }

  .topbar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.6rem 1.2rem;
    background: #1e293b;
    border-bottom: 1px solid #334155;
    flex-wrap: wrap;
  }

  .brand { font-weight: 700; font-size: 1.1rem; color: #38bdf8; white-space: nowrap; }

  .nav-links, .time-selector { display: flex; gap: 0.3rem; flex-wrap: wrap; }

  .nav-links button, .time-selector button {
    background: transparent;
    border: 1px solid #334155;
    color: #94a3b8;
    padding: 0.3rem 0.7rem;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
  }
  .nav-links button:hover, .time-selector button:hover { border-color: #38bdf8; color: #e2e8f0; }
  .nav-links button.active, .time-selector button.selected {
    background: #38bdf8;
    color: #0f172a;
    border-color: #38bdf8;
    font-weight: 600;
  }

  .time-selector { margin-left: auto; }

  .content { flex: 1; overflow-y: auto; padding: 1.5rem; }
</style>
