import { rmSync } from 'node:fs'
import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

/** O service worker do MSW vive em public/ (dev:mock) mas não deve ir pro build de produção. */
function dropMockWorker(): Plugin {
  return {
    name: 'drop-msw-worker',
    apply: 'build',
    closeBundle() {
      rmSync(resolve(import.meta.dirname, 'dist/mockServiceWorker.js'), { force: true })
    },
  }
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), mode === 'mock' ? null : dropMockWorker()],
  server: {
    port: 5173,
    // `?fixture=<nome>` (modo mock) lê contracts/fixtures, que fica fora de frontend/.
    fs: { allow: ['..'] },
    proxy: {
      '/api': 'http://127.0.0.1:8787',
      '/ws': { target: 'ws://127.0.0.1:8787', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
}))
