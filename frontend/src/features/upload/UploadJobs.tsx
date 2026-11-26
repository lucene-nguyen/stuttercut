import { useCallback, useEffect, useRef, useState } from 'react'

import {
  api,
  watchJob,
  type DetectOptions,
  type JobSummary,
  type ProgressEvent,
} from '../../api/client'
import { revealLabel } from '../../components/reveal'
import { statusView } from './status'
import { fmtTime } from '../review/logic'

const ACTIVE = new Set(['queued', 'processing', 'transcribed', 'rendering'])

const DEFAULT_OPTIONS: DetectOptions = {
  filler: true,
  repeat: true,
  pause: true,
  retake: true,
  pause_min_ms: 600,
}

export default function UploadJobs({ platform }: { platform: string }) {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [live, setLive] = useState<Record<string, ProgressEvent>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [options, setOptions] = useState(DEFAULT_OPTIONS)
  const watching = useRef(new Map<string, () => void>())

  const refresh = useCallback(() => {
    api.listJobs().then(setJobs, (e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    refresh()
    const map = watching.current
    return () => map.forEach((stop) => stop())
  }, [refresh])

  // One SSE stream per running job; the list is reloaded when it ends.
  useEffect(() => {
    for (const job of jobs) {
      if (!ACTIVE.has(job.status) || watching.current.has(job.id)) continue
      const stop = watchJob(
        job.id,
        (e) => setLive((m) => ({ ...m, [job.id]: e })),
        () => {
          watching.current.delete(job.id)
          refresh()
        },
      )
      watching.current.set(job.id, stop)
    }
  }, [jobs, refresh])

  async function send(file: File | undefined) {
    if (!file) return
    setError('')
    setBusy(true)
    try {
      await api.upload(file, options)
      refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const set = (patch: Partial<DetectOptions>) => setOptions((o) => ({ ...o, ...patch }))

  return (
    <main className="page">
      <section
        aria-labelledby="up"
        className="row"
        style={{ flexDirection: 'column', alignItems: 'stretch', gap: 16 }}
      >
        <h1 id="up">Clean up a video</h1>
        <label
          className={`drop${over ? ' over' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            void send(e.dataTransfer.files[0])
          }}
        >
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#7FB0FF"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2M7 9l5-5 5 5M12 4v12" />
          </svg>
          <span style={{ fontSize: 18, fontWeight: 500 }}>
            {busy ? 'Uploading…' : 'Drop a video here, or choose a file'}
          </span>
          <span className="muted" style={{ fontSize: 14 }}>
            MP4 or MOV, up to 3 minutes. Everything is processed on this computer.
          </span>
          <span className="btn primary" aria-hidden="true">
            Choose file
          </span>
          <input
            type="file"
            accept="video/mp4,video/quicktime,.mp4,.mov"
            aria-label="Choose a video"
            disabled={busy}
            onChange={(e) => {
              void send(e.target.files?.[0])
              e.target.value = ''
            }}
          />
        </label>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        <fieldset className="options">
          <legend>Detect and mark for removal</legend>
          <label>
            <input
              type="checkbox"
              checked={options.filler}
              onChange={(e) => set({ filler: e.target.checked })}
            />
            Filler words{' '}
            <span className="muted" style={{ fontSize: 13 }} lang="vi">
              (ờ, à, ừm, ừ)
            </span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={options.repeat}
              onChange={(e) => set({ repeat: e.target.checked })}
            />
            Repeated words
          </label>
          <label>
            <input
              type="checkbox"
              checked={options.pause}
              onChange={(e) => set({ pause: e.target.checked })}
            />
            Pauses longer than
            <input
              className="field"
              type="number"
              min={100}
              max={5000}
              step={50}
              value={options.pause_min_ms}
              aria-label="Pause threshold in milliseconds"
              style={{ width: 72 }}
              onChange={(e) => set({ pause_min_ms: Number(e.target.value) || 600 })}
            />
            ms
          </label>
          <label>
            <input
              type="checkbox"
              checked={options.retake}
              onChange={(e) => set({ retake: e.target.checked })}
            />
            Retakes &amp; false starts{' '}
            <span className="muted" style={{ fontSize: 13 }}>
              (LLM review)
            </span>
          </label>
        </fieldset>
      </section>

      <section aria-labelledby="jobs" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 id="jobs">Recent jobs</h2>
        {jobs.length === 0 ? (
          <p className="muted">No videos yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Video</th>
                  <th>Length</th>
                  <th>Status</th>
                  <th>Cuts</th>
                  <th>Time saved</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const s = statusView(job, live[job.id])
                  return (
                    <tr key={job.id} data-job={job.id}>
                      <td style={{ fontWeight: 500 }}>{job.name}</td>
                      <td className="mono">{job.duration_s ? fmtTime(job.duration_s) : '—'}</td>
                      <td aria-live="polite">
                        {s.tone === 'busy' ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <span style={{ color: 'var(--link)' }}>
                              {s.text}
                              {s.percent != null && ` · ${s.percent}%`}
                            </span>
                            <div
                              className="bar"
                              role="progressbar"
                              aria-label={s.text}
                              aria-valuenow={s.percent ?? undefined}
                              aria-valuemin={0}
                              aria-valuemax={100}
                            >
                              <div style={{ width: `${s.percent ?? 5}%` }} />
                            </div>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <span className={`badge ${s.tone}`} style={{ alignSelf: 'flex-start' }}>
                              {s.text}
                            </span>
                            {job.status === 'failed' && job.error && (
                              <span className="muted" style={{ fontSize: 13 }}>
                                {job.error.slice(0, 120)}. Cuts are saved.
                              </span>
                            )}
                          </div>
                        )}
                      </td>
                      <td>
                        {job.status === 'ready_for_review' || job.status === 'done' || job.cut_count
                          ? job.cut_count
                          : '—'}
                      </td>
                      <td className="mono">{job.saved_s > 0 ? `−${fmtTime(job.saved_s)}` : '—'}</td>
                      <td className="actions">
                        {job.status === 'failed' && (
                          <>
                            <a href={`#/diagnostics?job=${job.id}`}>View trace</a>
                            <button
                              className="btn"
                              onClick={() => void act(() => api.retry(job.id))}
                            >
                              Retry
                            </button>
                          </>
                        )}
                        {job.status === 'done' && (
                          <button
                            className="btn"
                            onClick={() => void act(() => api.reveal(job.id))}
                          >
                            {revealLabel(platform)}
                          </button>
                        )}
                        {(job.status === 'ready_for_review' || job.status === 'done') && (
                          <a
                            className={`btn${job.status === 'ready_for_review' ? ' primary' : ''}`}
                            href={`#/review/${job.id}`}
                          >
                            Review<span className="sr-only"> {job.name}</span>
                          </a>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}
