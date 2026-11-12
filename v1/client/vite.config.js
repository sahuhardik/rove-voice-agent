import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The build lands in `client/dist`, which is exactly where `server/config.py`
// looks for it (`Settings.client_dist`). The server mounts `dist/assets` and
// serves `dist/index.html` at `/`, so one build and one process is the whole
// deployment — the shape `docs/06` §8.1.1 picks for the spike.
//
// `base: './'` keeps the asset URLs relative, so the page also works when it is
// opened behind a path prefix or from the filesystem during a quick check.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // `npm run dev` talks to a server already running on 8080, so the dev
    // server and the Python process do not need to agree on anything else.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/healthz': { target: 'http://127.0.0.1:8080', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8080', ws: true },
    },
  },
})
