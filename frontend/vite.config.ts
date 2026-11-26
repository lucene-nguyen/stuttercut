/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    // STUTTERCUT_API lets the E2E run point the UI at its own API instance.
    proxy: { '/api': process.env.STUTTERCUT_API ?? 'http://127.0.0.1:8000' },
  },
  test: { exclude: ['e2e/**', 'node_modules/**'] },
})
