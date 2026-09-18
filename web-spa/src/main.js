import App from './App.svelte'
import { initDb } from './db.js'
import { dbReady, dbError } from './stores.js'

// Mount app immediately so loading spinner / layout is shown
const app = new App({
  target: document.getElementById('app'),
})

// Initialize sql.js database in background
initDb()
  .then(() => {
    dbReady.set(true)
  })
  .catch(err => {
    console.error('Failed to initialize database:', err)
    dbError.set(err.message || String(err))
  })

export default app
