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
      '/api': 'http://localhost:10000',
    },
  },
})

