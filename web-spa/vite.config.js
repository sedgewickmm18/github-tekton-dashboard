import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { viteStaticCopy } from 'vite-plugin-static-copy'

export default defineConfig({
  base: '/github-tekton-dashboard/',
  plugins: [
    svelte(),
    viteStaticCopy({
      targets: [
        {
          src: 'node_modules/sql.js/dist/sql-wasm*.wasm',
          dest: '.'
        }
      ]
    })
  ],
  build: {
    outDir: 'dist'
  }
})
