import { useCallback, useEffect, useState } from 'react'

import {
  api,
  diagnosticsApi,
  type Environment,
  type JobSummary,
  type LogEntry,
  type Metrics,
  type Trace,
} from '../../api/client'
import { fmtTime } from '../review/logic'
import {
  LEVELS,
  STEP_COLOR,
  STEP_LABEL,
  errorDetails,
  fmtMemory,
  fmtPercent,
  jobFromHash,
  levelCounts,
  levelLabel,
  waterfall,
  type LevelFilter,
} from './logic'

const LEVEL_TONE: Record<string, string> = { ERROR: 'err', WARNING: 'warn', INFO: 'idle' }

export function TraceView({ trace, env }: { trace: Trace; env: Environment | null }) {
  const [copied, setCopied] = useState(false)
  const bars = waterfall(trace)
  const failed = trace.status === 'failed'
  const stderr = trace.errors.find((e) => e.ffmpeg_stderr)?.ffmpeg_stderr
  return (
    <div
      className="card"
      style={{ flex: '3 1 560px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 10 }}
    >
      <div className="row spread muted" style={{ fontSize: 13 }}>
        <span>
          <span style={{ color: 'var(--text)', fontWeight: 500 }}>{trace.name}</span> · trace{' '}
          {trace.id}
        </span>
        <span className="mono">total {trace.total_s.toFixed(1)}s</span>
      </div>
      {bars.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          No steps recorded yet.
        </p>
      ) : (
        <div className="waterfall" role="table" aria-label={`Steps of ${trace.name}`}>
          {bars.map((b, i) => (
            <div key={i} role="row" className="wf-row">
              <span
                role="rowheader"
                className="mono"
                style={{ color: b.failed ? 'var(--err)' : 'var(--text-2)' }}
              >
                {b.step}
                {b.failed && <span className="sr-only"> (failed)</span>}
              </span>
              <span role="cell" className="wf-track">
                <span
                  className="wf-bar"
                  style={{ left: `${b.leftPct}%`, width: `${b.widthPct}%`, background: b.color }}
                />
              </span>
              <span
                role="cell"
                className="mono"
                style={{ textAlign: 'right', color: 'var(--text-2)' }}
              >
                {b.durationS.toFixed(1)}s
              </span>
            </div>
          ))}
        </div>
      )}
      {failed && (
        <div
          role="alert"
          className="alert"
          style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}
        >
          <strong style={{ fontWeight: 500 }}>
            {trace.failed_step} failed · {trace.error}
          </strong>
          {stderr && <pre className="stderr">{stderr.trim()}</pre>}
          <div>
            <button
              className="btn small"
              style={{ borderColor: 'var(--err-line)', color: '#FFD6CF' }}
              onClick={() =>
                void navigator.clipboard
                  .writeText(errorDetails(trace, env))
                  .then(() => setCopied(true))
              }
            >
              {copied ? 'Copied' : 'Copy error details'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Diagnostics() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [env, setEnv] = useState<Environment | null>(null)
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [jobId, setJobId] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : jobFromHash(window.location.hash),
  )
  const [trace, setTrace] = useState<Trace | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [level, setLevel] = useState<LevelFilter>('all')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')

  const fail = (e: Error) => setError(e.message)
  const load = useCallback(() => {
    diagnosticsApi.metrics().then(setMetrics, fail)
    diagnosticsApi.environment().then(setEnv, fail)
    diagnosticsApi.logs().then(setLogs, fail)
    api.listJobs().then((js) => {
      setJobs(js.slice(0, 12))
      setJobId((cur) => cur ?? js[0]?.id ?? null)
    }, fail)
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    if (jobId) diagnosticsApi.trace(jobId).then(setTrace, fail)
  }, [jobId])

  const counts = levelCounts(logs)
  const shown = logs.filter((e) => level === 'all' || e.level === level).slice(0, 200)
  const order = Object.keys(STEP_LABEL) // pipeline order, unknown steps last
  const steps = Object.entries(metrics?.avg_step_s ?? {}).sort(
    ([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99),
  )
  const maxStep = Math.max(1, ...steps.map(([, v]) => v))
  const done = metrics?.by_status.done ?? 0
  const ready = metrics?.by_status.ready_for_review ?? 0
  const failedJobs = metrics?.by_status.failed ?? 0

  return (
    <main className="page" style={{ maxWidth: 1280 }}>
      <div className="row spread">
        <h1 id="mt" style={{ fontSize: 22 }}>
          Metrics · last {metrics?.days ?? 7} days
        </h1>
        <div className="row">
          <button
            className="btn"
            onClick={() =>
              void diagnosticsApi.openLogFolder().then(() => setNote('Log folder opened.'), fail)
            }
          >
            Open log folder
          </button>
          <button
            className="btn"
            onClick={() =>
              void diagnosticsApi
                .exportZip()
                .then((name) => setNote(`Saved ${name} to your downloads.`), fail)
            }
          >
            Export diagnostics (.zip)
          </button>
        </div>
      </div>
      {env && (
        <p className="mono muted" style={{ margin: '-16px 0 0', fontSize: 13 }}>
          {env.os} · {env.machine} · {env.ram_gb} GB RAM · Python {env.python} ·{' '}
          {env.packages.torch ? `torch ${env.packages.torch}` : 'no torch'} ·{' '}
          {env.ffmpeg?.split(' Copyright')[0] ?? 'FFmpeg not found'}
        </p>
      )}
      {(error || note) && (
        <div role={error ? 'alert' : 'status'} className={error ? 'alert' : 'card'}>
          {error || note}
        </div>
      )}

      <section aria-labelledby="mt" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="cards">
          <div className="card">
            <div className="muted" style={{ fontSize: 13 }}>
              Jobs
            </div>
            <div className="big" data-testid="metric-jobs">
              {metrics?.jobs ?? '—'}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {done} rendered · {ready} to review · {failedJobs} failed
            </div>
          </div>
          <div className="card">
            <div className="muted" style={{ fontSize: 13 }}>
              Success rate
            </div>
            <div className="big" style={{ color: 'var(--ok)' }}>
              {fmtPercent(metrics?.success_rate ?? null)}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              {Object.keys(metrics?.failures_by_step ?? {}).length
                ? `failures: ${Object.entries(metrics!.failures_by_step)
                    .map(([s, n]) => `${s} ${n}`)
                    .join(' · ')}`
                : 'no failures'}
            </div>
          </div>
          <div className="card">
            <div className="muted" style={{ fontSize: 13 }}>
              Avg processing
            </div>
            <div className="big mono">
              {metrics?.avg_processing_s != null ? fmtTime(metrics.avg_processing_s) : '—'}
            </div>
            <div className="muted" style={{ fontSize: 13 }}>
              per job · avg clip {metrics?.avg_clip_s != null ? fmtTime(metrics.avg_clip_s) : '—'}
            </div>
          </div>
          <div className="card">
            <div className="muted" style={{ fontSize: 13 }}>
              Peak memory
            </div>
            <div className="big">{fmtMemory(metrics?.peak_rss_mb ?? null)}</div>
            <div className="muted" style={{ fontSize: 13 }}>
              worker RSS{metrics?.peak_rss_job ? ` · job ${metrics.peak_rss_job}` : ''}
            </div>
          </div>
        </div>
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <h2 style={{ fontSize: 16 }}>Average time per step</h2>
          {steps.length === 0 && (
            <p className="muted" style={{ margin: 0 }}>
              No finished steps yet.
            </p>
          )}
          {steps.map(([step, s]) => (
            <div key={step} className="step-row">
              <span style={{ color: 'var(--text-2)' }}>{STEP_LABEL[step] ?? step}</span>
              <span className="step-track" aria-hidden="true">
                <span
                  style={{
                    width: `${Math.max(1.5, (s / maxStep) * 100)}%`,
                    background: STEP_COLOR[step] ?? '#8B93A3',
                  }}
                />
              </span>
              <span className="mono" style={{ textAlign: 'right', color: 'var(--text-2)' }}>
                {s.toFixed(1)}s
              </span>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="tc" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 id="tc">Job traces</h2>
        <div className="row" style={{ alignItems: 'flex-start', gap: 16 }}>
          <div role="group" aria-label="Recent jobs" className="job-picker">
            {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
            {jobs.map((j) => (
              <button key={j.id} aria-pressed={j.id === jobId} onClick={() => setJobId(j.id)}>
                <span style={{ minWidth: 0 }}>
                  <span className="name">{j.name}</span>
                  <span className="mono muted" style={{ fontSize: 12 }}>
                    {j.id} ·{' '}
                    {new Date(j.created_at).toLocaleString(undefined, {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </span>
                <span
                  className={`badge ${j.status === 'failed' ? 'err' : j.status === 'done' ? 'ok' : 'idle'}`}
                >
                  {j.status === 'failed'
                    ? 'Failed'
                    : j.status === 'done'
                      ? 'Done'
                      : j.status.replace(/_/g, ' ')}
                </span>
              </button>
            ))}
          </div>
          {trace && <TraceView trace={trace} env={env} />}
        </div>
      </section>

      <section aria-labelledby="lg" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="row spread">
          <h2 id="lg">Logs</h2>
          <div role="group" aria-label="Filter by level" className="row" style={{ gap: 6 }}>
            {LEVELS.map((l) => (
              <button
                key={l}
                className="chip"
                aria-pressed={level === l}
                onClick={() => setLevel(l)}
              >
                {levelLabel(l)} {counts[l]}
              </button>
            ))}
          </div>
        </div>
        <div className="table-wrap" style={{ background: 'var(--panel)' }}>
          <table className="mono" style={{ fontSize: 13, minWidth: 860 }}>
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Job</th>
                <th>Step</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((e, i) => (
                <tr key={i}>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>
                    {e.ts.slice(5).replace('T', ' ')}
                  </td>
                  <td>
                    <span
                      className={`badge ${LEVEL_TONE[e.level] ?? 'idle'}`}
                      style={{ fontSize: 12 }}
                    >
                      {levelLabel(e.level)}
                    </span>
                  </td>
                  <td style={{ whiteSpace: 'nowrap', color: 'var(--text-2)' }}>
                    {e.job_id ?? (e.source === 'ui' ? 'ui' : 'app')}
                  </td>
                  <td style={{ color: 'var(--text-2)' }}>{e.step ?? ''}</td>
                  <td>{e.msg}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span className="muted" style={{ fontSize: 13 }}>
          Logs are JSON Lines in <span className="mono">{env?.log_dir ?? '…'}</span> · rotated at{' '}
          {Math.round(Number(env?.settings.log?.max_bytes ?? 5242880) / 2 ** 20)} MB,{' '}
          {String(env?.settings.log?.backup_count ?? 3)} old files kept.
        </span>
      </section>
    </main>
  )
}
