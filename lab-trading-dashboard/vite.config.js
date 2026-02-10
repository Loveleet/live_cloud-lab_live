import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// Relative base so assets work on GitHub Pages (e.g. loveleet.github.io/lab_live/) and anywhere
export default defineConfig({
  base: process.env.VITE_BASE_PATH || './',
  esbuild: {
    minify: false,
  },
  plugins: [react()],
  server: {
    proxy: {
      // Only proxy /api/... (e.g. /api/tunnel-url), not /api-config.json (so config is served from public/ or returns 404)
      // Proxies to local server (server-local.js) on port 3001, or cloud server on 10000 if local not available
      '/api/': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        // Fallback to cloud if local server not available (optional - you can remove this if you only want local)
        // configure: (proxy, options) => {
        //   proxy.on('error', (err, req, res) => {
        //     console.log('[Vite Proxy] Local server not available, requests will fail');
        //   });
        // }
      },
    },
  },
})

