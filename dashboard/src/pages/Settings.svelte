<script>
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  let config = {
    apiKey: '',
    pipelineId: '',
    region: '',
    triggerName: '',
    githubToken: '',
  }

  let meta = null
  let running = false
  let runOutput = ''
  let loadError = null
  let days = 30

  async function loadMeta() {
    try {
      const rows = await invoke('get_scrape_meta')
      meta = rows?.[0] || null
    } catch (e) {
      loadError = String(e)
    }
  }

  async function triggerScrape() {
    running = true; runOutput = ''
    try {
      runOutput = await invoke('run_scraper', { days })
      await loadMeta()
    } catch (e) {
      runOutput = '❌ ' + String(e)
    } finally {
      running = false
    }
  }

  onMount(loadMeta)
</script>

<div class="page">
  <h1>Settings</h1>

  <section class="card">
    <h2>Pipeline Configuration</h2>
    <p class="hint">Edit <code>scraper/pipeline.env</code> to persist changes. Values shown here are for reference.</p>
    <div class="form">
      <label>
        IBM Cloud API Key
        <input type="password" bind:value={config.apiKey} placeholder="•••••••••••••" />
      </label>
      <label>
        Pipeline ID
        <input type="text" bind:value={config.pipelineId} placeholder="e.g. abcd-1234-..." />
      </label>
      <label>
        Region
        <input type="text" bind:value={config.region} placeholder="e.g. us-south" />
      </label>
      <label>
        Trigger Name
        <input type="text" bind:value={config.triggerName} placeholder="e.g. pr-trigger" />
      </label>
      <label>
        GitHub Token (optional)
        <input type="password" bind:value={config.githubToken} placeholder="ghp_..." />
      </label>
    </div>
  </section>

  <section class="card">
    <h2>Manual Scraper Run</h2>
    {#if meta}
      <p class="meta-info">
        Last scraped: <b>{meta.last_scraped_at ?? 'never'}</b>
        · {meta.run_count ?? 0} runs stored
        · window: {meta.days ?? '?'} days
      </p>
    {:else if loadError}
      <p class="err">{loadError}</p>
    {:else}
      <p class="muted">No scrape metadata found. Run the scraper first.</p>
    {/if}

    <div class="trigger-row">
      <label>
        Days to scrape
        <input type="number" bind:value={days} min="1" max="365" />
      </label>
      <button class="btn-run" on:click={triggerScrape} disabled={running}>
        {running ? '⏳ Running…' : '▶ Run Scraper'}
      </button>
    </div>

    {#if runOutput}
      <pre class="output">{runOutput}</pre>
    {/if}
  </section>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 1.5rem; max-width: 720px; }
  h1 { font-size: 1.4rem; font-weight: 700; color: #38bdf8; }
  h2 { font-size: 1rem; font-weight: 600; margin-bottom: 0.8rem; }

  .card {
    background: #1e293b; border: 1px solid #334155;
    border-radius: 10px; padding: 1.2rem;
  }
  .hint { font-size: 0.8rem; color: #64748b; margin-bottom: 1rem; }
  code { background: #0f172a; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.8rem; }

  .form { display: flex; flex-direction: column; gap: 0.6rem; }
  label { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.82rem; color: #94a3b8; }
  input[type="text"], input[type="password"], input[type="number"] {
    background: #0f172a; border: 1px solid #334155;
    border-radius: 6px; color: #e2e8f0;
    padding: 0.4rem 0.6rem; font-size: 0.9rem;
    outline: none; transition: border-color 0.15s;
  }
  input:focus { border-color: #38bdf8; }
  input[type="number"] { width: 80px; }

  .meta-info { font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.8rem; }
  .muted { color: #64748b; font-size: 0.85rem; margin-bottom: 0.8rem; }
  .err { color: #f87171; font-size: 0.85rem; }

  .trigger-row { display: flex; align-items: flex-end; gap: 1rem; margin-top: 0.6rem; }
  .btn-run {
    background: #38bdf8; color: #0f172a; border: none;
    padding: 0.45rem 1.2rem; border-radius: 6px; font-weight: 700;
    cursor: pointer; font-size: 0.9rem; transition: opacity 0.15s;
  }
  .btn-run:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-run:hover:not(:disabled) { opacity: 0.85; }

  pre.output {
    background: #0f172a; border: 1px solid #334155;
    border-radius: 6px; padding: 0.8rem;
    font-size: 0.78rem; color: #94a3b8;
    white-space: pre-wrap; max-height: 300px; overflow-y: auto;
    margin-top: 0.8rem;
  }
</style>
