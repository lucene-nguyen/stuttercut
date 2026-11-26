import type { JobSummary, ProgressEvent } from '../../api/client'

export function statusView(
  job: JobSummary,
  live?: ProgressEvent,
): { text: string; tone: string; percent: number | null } {
  const step = live?.label ?? job.step_label
  const percent = live?.percent ?? job.progress
  switch (job.status) {
    case 'queued':
      return { text: 'Queued', tone: 'idle', percent: null }
    case 'processing':
    case 'transcribed':
      return { text: step ?? 'Processing', tone: 'busy', percent }
    case 'rendering':
      return { text: step ?? 'Rendering', tone: 'busy', percent }
    case 'ready_for_review':
      return { text: 'Ready for review', tone: 'warn', percent: null }
    case 'done':
      return { text: 'Rendered', tone: 'ok', percent: null }
    case 'failed':
      return { text: `Failed at ${job.failed_step ?? 'unknown step'}`, tone: 'err', percent: null }
    default:
      return { text: job.status, tone: 'idle', percent: null }
  }
}
