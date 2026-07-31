// vitest/config, not vite: the same defineConfig widened to accept the `test` block
// below, which vite's own types reject.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    // Per-file, via the `@vitest-environment jsdom` docblock. The pure lib tests are
    // the large majority and run an order of magnitude faster in node; paying jsdom's
    // startup for all of them to suit the few component tests is the wrong default.
    environment: 'node',
    globals: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
