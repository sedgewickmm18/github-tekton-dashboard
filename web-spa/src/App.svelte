<script>
  import { onMount } from 'svelte'
  import { timeWindow, currentPage, dbReady, dbError } from './stores.js'
  import { getScrapeMeta } from './db.js'
  import Overview  from './pages/Overview.svelte'
  import PRDetail  from './pages/PRDetail.svelte'
  import Errors    from './pages/Errors.svelte'
  import Stages    from './pages/Stages.svelte'
  import Reruns    from './pages/Reruns.svelte'

  const pages = [
    { id: 'overview', label: '📊 Overview' },
    { id: 'prs',      label: '🔀 PRs' },
    { id: 'errors',   label: '❌ Errors' },
    { id: 'stages',   label: '📋 Stages' },
    { id: 'reruns',   label: '🔄 Reruns' },
  ]

  const windows = [
    { value: 7,   label: '7 days' },
    { value: 30,  label: '30 days' },
    { value: 90,  label: '90 days' },
  ]

  let lastScraped = ''

  $: if ($dbReady) {
    getScrapeMeta()
      .then(rows => {
        if (rows && rows.length > 0 && rows[0].last_scraped_at) {
          const d = new Date(rows[0].last_scraped_at)
          lastScraped = isNaN(d.getTime()) ? rows[0].last_scraped_at : d.toLocaleString()
        }
      })
      .catch(() => {})
  }
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

    {#if lastScraped}
      <div class="last-scraped-badge" title="Last scraped timestamp">
        🕒 {lastScraped}
      </div>
    {/if}

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
    {#if $dbError}
      <div class="global-error">
        <h2>⚠ Failed to load database</h2>
        <p>{$dbError}</p>
        <p class="help">Ensure <code>dashboard.db</code> exists and is accessible.</p>
      </div>
    {:else if !$dbReady}
      <div class="global-loading">
        <div class="spinner"></div>
        <p>Loading database…</p>
      </div>
    {:else}
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
      {/if}
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

  .last-scraped-badge {
    font-size: 0.78rem;
    color: #94a3b8;
    background: #0f172a;
    border: 1px solid #334155;
    padding: 0.25rem 0.6rem;
    border-radius: 6px;
    margin-left: auto;
    white-space: nowrap;
  }

  .time-selector {
    /* If badge is present, it's pushed right by badge's margin-left: auto */
    margin-left: 0;
  }
  /* Fallback if no badge is shown yet */
  .last-scraped-badge + .time-selector,
  .topbar:not(:has(.last-scraped-badge)) .time-selector {
    margin-left: auto;
  }

  .content { flex: 1; overflow-y: auto; padding: 1.5rem; }

  .global-loading, .global-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 60vh;
    gap: 1rem;
    text-align: center;
  }

  .spinner {
    width: 40px;
    height: 40px;
    border: 4px solid #334155;
    border-top-color: #38bdf8;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .global-error h2 { color: #f87171; }
  .global-error .help { color: #64748b; font-size: 0.85rem; }
  .global-error code { background: #1e293b; padding: 0.2rem 0.4rem; border-radius: 4px; }
</style>
