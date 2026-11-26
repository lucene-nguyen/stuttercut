import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App'
import { parseRoute } from './routes'
import { revealLabel } from './components/reveal'
import { statusView } from './features/upload/status'
import type { JobSummary } from './api/client'

describe('App', () => {
  it('renders the header and the upload screen', () => {
    const html = renderToString(<App />)
    expect(html).toContain('StutterCut')
    expect(html).toContain('Clean up a video')
  })
  it('parses hash routes', () => {
    expect(parseRoute('#/review/abc123')).toEqual({ page: 'review', id: 'abc123' })
    expect(parseRoute('#/diagnostics?job=x')).toEqual({ page: 'diagnostics' })
    expect(parseRoute('')).toEqual({ page: 'jobs' })
  })
  it('names the file manager per platform', () => {
    expect(revealLabel('darwin')).toBe('Show in Finder')
    expect(revealLabel('win32')).toBe('Show in Explorer')
    expect(revealLabel('linux')).toBe('Show in folder')
  })
})

describe('job status', () => {
  const job = (extra: Partial<JobSummary>): JobSummary => ({
    id: 'j', name: 'a.mp4', status: 'queued', step: null, step_label: null, progress: null,
    failed_step: null, error: null, duration_s: 10, created_at: '', cut_count: 0, saved_s: 0,
    output_path: null, xml_path: null, ...extra,
  }) // prettier-ignore
  it('shows live progress for a running step', () => {
    const s = statusView(job({ status: 'processing', step_label: 'Transcribing', progress: 10 }), {
      step: 'transcribe',
      label: 'Transcribing',
      percent: 62,
    })
    expect(s).toEqual({ text: 'Transcribing', tone: 'busy', percent: 62 })
  })
  it('names the failed step', () => {
    expect(statusView(job({ status: 'failed', failed_step: 'render' })).text).toBe(
      'Failed at render',
    )
    expect(statusView(job({ status: 'ready_for_review' })).text).toBe('Ready for review')
  })
})
