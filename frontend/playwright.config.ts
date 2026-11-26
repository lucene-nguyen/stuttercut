// E2E: the real API (fake transcriber, temp data folder) + the Vite UI. Run: npm run e2e
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { defineConfig } from '@playwright/test'

const repo = resolve(import.meta.dirname, '..')
const tmp = process.env.E2E_TMP ?? mkdtempSync(join(tmpdir(), 'stuttercut-e2e-'))
process.env.E2E_TMP = tmp // the config is loaded again in each worker: keep one folder
const media = join(tmp, 'media')
const venvPython = join(
  repo,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : 'python')
const API_PORT = 8765
const UI_PORT = 5174

function makeClip(name: string, seconds: number, size: string, fps: number) {
  const out = join(media, name)
  if (existsSync(out)) return
  execFileSync('ffmpeg', [
    ...['-nostdin', '-loglevel', 'error', '-y'],
    ...['-f', 'lavfi', '-i', `testsrc=size=${size}:rate=${fps}:duration=${seconds}`],
    ...['-f', 'lavfi', '-i', `sine=frequency=330:sample_rate=44100:duration=${seconds}`],
    ...['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', out],
  ])
}
mkdirSync(media, { recursive: true })
makeClip('bài nói thử.mp4', 10, '320x240', 25)
makeClip('dài quá.mp4', 240, '64x48', 5)

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  workers: 1, // one API, one worker process: one job at a time
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${UI_PORT}`,
    channel: process.env.PW_CHANNEL || undefined, // e.g. "chrome" to use the installed browser
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn stuttercut.api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: tmp, // no .env from the repo: the developer's own settings stay out of the test
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      timeout: 60_000,
      env: {
        STUTTERCUT_HOME: join(tmp, 'home'),
        STUTTERCUT_OUTPUT_DIR: join(tmp, 'out'),
        STUTTERCUT_FAKE_TRANSCRIBER: join(repo, 'tests', 'fixtures', 'review_clip.json'),
        STUTTERCUT_LLM_ENABLED: 'false',
      },
    },
    {
      command: `npx vite --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}`,
      timeout: 60_000,
      env: { STUTTERCUT_API: `http://127.0.0.1:${API_PORT}` },
    },
  ],
})
