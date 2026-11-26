import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { Environment, LogEntry, Trace } from '../../api/client'
import { TraceView } from './Diagnostics'
import {
  ERROR_COLOR,
  errorDetails,
  fmtMemory,
  fmtPercent,
  jobFromHash,
  levelCounts,
  waterfall,
} from './logic'

const failed: Trace = {
  id: 'j-0141', name: 'bài 3.mp4', status: 'failed', failed_step: 'render',
  error: 'RenderError: encode: ffmpeg failed with h264_nvenc', created_at: '2026-11-26T08:00:00Z',
  total_s: 40,
  spans: [
    { step: 'extract_audio', status: 'ok', error: null, started_at: '', duration_s: 2, offset_s: 0 },
    { step: 'transcribe', status: 'ok', error: null, started_at: '', duration_s: 30, offset_s: 2 },
    { step: 'detect', status: 'ok', error: null, started_at: '', duration_s: 0.1, offset_s: 32 },
    { step: 'render', status: 'error', error: 'x', started_at: '', duration_s: 6, offset_s: 34 },
  ],
  errors: [{ step: 'render', ffmpeg_stderr: 'OpenEncodeSessionEx failed: out of memory\n' }],
} // prettier-ignore
const env = {
  os: 'Windows-11',
  machine: 'AMD64',
  ram_gb: 15.6,
  ffmpeg: 'ffmpeg version 8.1',
} as Environment

describe('waterfall', () => {
  it('places each span on the job timeline and keeps tiny ones visible', () => {
    const bars = waterfall(failed)
    expect(bars.map((b) => [b.step, b.leftPct, b.widthPct])).toEqual([
      ['extract_audio', 0, 5], ['transcribe', 5, 75], ['detect', 80, 0.8], ['render', 85, 15],
    ]) // prettier-ignore
    expect(bars[3]).toMatchObject({ failed: true, color: ERROR_COLOR })
  })
})

describe('logs and formats', () => {
  it('counts levels', () => {
    const logs = [{ level: 'ERROR' }, { level: 'INFO' }, { level: 'INFO' }] as LogEntry[]
    expect(levelCounts(logs)).toEqual({ all: 3, ERROR: 1, WARNING: 0, INFO: 2 })
  })
  it('formats memory, rates and reads the job from the hash', () => {
    expect(fmtMemory(6963)).toBe('6.8 GB')
    expect(fmtMemory(950)).toBe('950 MB')
    expect(fmtPercent(0.913)).toBe('91%')
    expect(fmtPercent(null)).toBe('—')
    expect(jobFromHash('#/diagnostics?job=abc123')).toBe('abc123')
    expect(jobFromHash('#/diagnostics')).toBeNull()
  })
})

describe('failed trace', () => {
  it('copies the step, error, stderr and environment', () => {
    const text = errorDetails(failed, env)
    expect(text).toContain('status: failed at render')
    expect(text).toContain('OpenEncodeSessionEx failed')
    expect(text).toContain('env: Windows-11 · AMD64')
  })
  it('shows the failed step, stderr and the copy button', () => {
    const html = renderToString(<TraceView trace={failed} env={env} />).replace(/<!-- -->/g, '')
    expect(html).toContain('render failed')
    expect(html).toContain('OpenEncodeSessionEx failed')
    expect(html).toContain('Copy error details')
  })
})
