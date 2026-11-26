// Pure Diagnostics logic: waterfall geometry, level counts, error report text, number formats.
import type { Environment, LogEntry, Trace } from '../../api/client'

export const STEP_COLOR: Record<string, string> = {
  extract_audio: '#8B93A3',
  preview: '#8B93A3',
  load_model: '#5B9BFF',
  transcribe: '#5B9BFF',
  detect: '#4FD1C5',
  unload_asr: '#8B93A3',
  llm_load: '#C4A3FF',
  llm_review: '#C4A3FF',
  render: '#F2B544',
}
export const ERROR_COLOR = '#E5534B'

export const STEP_LABEL: Record<string, string> = {
  extract_audio: 'Extract audio',
  preview: 'Preview',
  load_model: 'Load model',
  transcribe: 'Transcribe',
  detect: 'Detect (rules)',
  unload_asr: 'Free ASR memory',
  llm_load: 'Load LLM',
  llm_review: 'LLM review',
  render: 'Render',
}

export interface Bar {
  step: string
  leftPct: number
  widthPct: number
  color: string
  durationS: number
  failed: boolean
}

/** One bar per span, placed on the job's timeline; tiny steps stay visible (min 0.8%). */
export function waterfall(trace: Trace): Bar[] {
  const total = trace.total_s || 1
  return trace.spans.map((s) => ({
    step: s.step,
    leftPct: Math.min(100, (s.offset_s / total) * 100),
    widthPct: Math.max(0.8, (s.duration_s / total) * 100),
    color: s.status === 'error' ? ERROR_COLOR : (STEP_COLOR[s.step] ?? '#8B93A3'),
    durationS: s.duration_s,
    failed: s.status === 'error',
  }))
}

export const LEVELS = ['all', 'ERROR', 'WARNING', 'INFO'] as const
export type LevelFilter = (typeof LEVELS)[number]

export function levelCounts(logs: LogEntry[]): Record<LevelFilter, number> {
  const out: Record<LevelFilter, number> = { all: logs.length, ERROR: 0, WARNING: 0, INFO: 0 }
  for (const e of logs) if (e.level in out) out[e.level as LevelFilter]++
  return out
}

/** What "Copy error details" puts on the clipboard (no transcript text: ids, steps, errors). */
export function errorDetails(trace: Trace, env: Environment | null): string {
  const lines = [
    `StutterCut job ${trace.id} (${trace.name})`,
    `status: ${trace.status}${trace.failed_step ? ` at ${trace.failed_step}` : ''}`,
    `error: ${trace.error ?? '-'}`,
    `steps: ${trace.spans.map((s) => `${s.step} ${s.duration_s.toFixed(1)}s ${s.status}`).join(', ')}`,
  ]
  for (const e of trace.errors) {
    if (e.ffmpeg_stderr) lines.push('', 'ffmpeg stderr:', e.ffmpeg_stderr.trim())
    if (e.exc) lines.push('', 'traceback:', e.exc.trim())
  }
  if (env)
    lines.push(
      '',
      `env: ${env.os} · ${env.machine} · RAM ${env.ram_gb} GB · ${env.ffmpeg ?? 'no ffmpeg'}`,
    )
  return lines.join('\n')
}

/** 6.8 GB / 950 MB */
export function fmtMemory(mb: number | null): string {
  if (mb == null) return '—'
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`
}

export function fmtPercent(rate: number | null): string {
  return rate == null ? '—' : `${Math.round(rate * 100)}%`
}

/** "WARNING" is shown as Warn, like the design. */
export function levelLabel(level: string): string {
  return { all: 'All', ERROR: 'Error', WARNING: 'Warn', INFO: 'Info' }[level] ?? level
}

/** #/diagnostics?job=<id> -> the job to open first. */
export function jobFromHash(hash: string): string | null {
  return /[?&]job=([\w-]+)/.exec(hash)?.[1] ?? null
}
