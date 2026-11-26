// REST + SSE client for the StutterCut API (design doc "API design"). Same origin: Vite proxies /api.

export type Reason = 'filler' | 'repeat' | 'pause' | 'retake'
export type Status =
  | 'queued'
  | 'processing'
  | 'transcribed'
  | 'ready_for_review'
  | 'rendering'
  | 'done'
  | 'failed'
  | 'cancelled'

export interface JobSummary {
  id: string
  name: string
  status: Status
  step: string | null
  step_label: string | null
  progress: number | null
  failed_step: string | null
  error: string | null
  duration_s: number | null
  created_at: string
  cut_count: number
  saved_s: number
  output_path: string | null
  xml_path: string | null
}

export interface Word {
  i: number
  text: string
  start: number
  end: number
}

export interface Cut {
  id: number
  start_s: number
  end_s: number
  reason: Reason
  source: string
  confidence: number
  tier: 'sure' | 'unsure'
  kept: number
  approved: number
  decided_at: string | null
  llm_verdict: string | null
  llm_reason: string | null
}

export interface JobDetail extends Omit<JobSummary, 'cut_count'> {
  cut_count?: number
  words: Word[]
  cuts: Cut[]
}

export interface DetectOptions {
  filler: boolean
  repeat: boolean
  pause: boolean
  retake: boolean
  pause_min_ms: number
}

export type RenderFormat = 'mp4' | 'xml' | 'both'

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(res.status, message)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<{ status: string; platform: string }>('/api/health'),
  listJobs: () => request<JobSummary[]>('/api/jobs'),
  getJob: (id: string) => request<JobDetail>(`/api/jobs/${id}`),
  upload: (file: File, options: DetectOptions) =>
    request<JobSummary>(
      `/api/jobs?name=${encodeURIComponent(file.name)}&options=${encodeURIComponent(JSON.stringify(options))}`,
      { method: 'POST', body: file },
    ),
  decide: (id: string, cutId: number, kept: boolean) =>
    request<{ saved_s: number }>(`/api/jobs/${id}/cuts/${cutId}`, json('PATCH', { kept })),
  bulk: (id: string, action: 'approve_sure' | 'cut_all' | 'keep_all') =>
    request<{ changed: number; saved_s: number }>(
      `/api/jobs/${id}/cuts:bulk`,
      json('POST', { action }),
    ),
  addCut: (id: string, start_s: number, end_s: number, reason: Reason) =>
    request<{ id: number; saved_s: number }>(
      `/api/jobs/${id}/cuts`,
      json('POST', { start_s, end_s, reason }),
    ),
  render: (id: string, format: RenderFormat, folder: string) =>
    request<JobSummary>(
      `/api/jobs/${id}/render`,
      json('POST', { format, folder: folder.trim() || null }),
    ),
  retry: (id: string) => request<JobSummary>(`/api/jobs/${id}/retry`, { method: 'POST' }),
  reveal: (id: string) => request<void>(`/api/jobs/${id}/reveal`, { method: 'POST' }),
  previewUrl: (id: string) => `/api/jobs/${id}/preview`,
}

export interface ProgressEvent {
  step: string
  label: string | null
  percent: number | null
}

/** Live progress of one job; calls onEnd once with the final row, then closes. */
export function watchJob(
  id: string,
  onProgress: (e: ProgressEvent) => void,
  onEnd: (job: JobSummary) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${id}/events`)
  source.addEventListener('progress', (e) => onProgress(JSON.parse((e as MessageEvent).data)))
  for (const kind of ['ready', 'done', 'failed']) {
    source.addEventListener(kind, (e) => {
      source.close()
      onEnd(JSON.parse((e as MessageEvent).data))
    })
  }
  return () => source.close()
}
