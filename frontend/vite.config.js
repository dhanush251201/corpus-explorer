import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Only the local dev and preview servers use this: they forward /api to the
  // backend so the page and the API share an origin. A deployed build calls the
  // address in public/config.js instead.
  const proxy = { '/api': { target: env.DEV_API_TARGET || 'http://localhost:8000', changeOrigin: true } }

  return {
    plugins: [react()],
    // Relative asset paths, so the build works from any directory on any host.
    base: './',
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
    build: { outDir: 'dist', emptyOutDir: true },
  }
})
