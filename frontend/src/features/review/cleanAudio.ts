// Pure clean-preview logic (ADR 0005): source <-> clean time, the Web Audio schedule of the
// plan's keep-segments, and cut edge nudging. No DOM, no AudioContext: unit-tested in vitest.

export interface Keep {
  start_s: number
  end_s: number
}

export interface Plan {
  keep_segments: Keep[]
  fade_ms: number
  duration_s: number
}

const EPS = 1e-6

/** Source time -> time in the clean video. Inside a cut: where the next keep-segment starts. */
export function toClean(t: number, keeps: Keep[]): number {
  let clean = 0
  for (const k of keeps) {
    if (t < k.start_s) return clean
    if (t < k.end_s) return clean + (t - k.start_s)
    clean += k.end_s - k.start_s
  }
  return clean
}

/** Clean time -> source time (the inverse of toClean on the kept parts). */
export function toSource(c: number, keeps: Keep[]): number {
  let left = Math.max(0, c)
  for (const k of keeps) {
    const len = k.end_s - k.start_s
    if (left < len) return k.start_s + left
    left -= len
  }
  return keeps.length ? keeps[keeps.length - 1].end_s : 0
}

export function cleanLength(keeps: Keep[]): number {
  return keeps.reduce((s, k) => s + (k.end_s - k.start_s), 0)
}

/** A playable source position: t itself inside a keep-segment, else the next segment's start;
 * null after the last one (the clean video has ended). */
export function snapToKeep(t: number, keeps: Keep[]): number | null {
  for (const k of keeps) {
    if (t < k.start_s) return k.start_s
    if (t < k.end_s - EPS) return t
  }
  return null
}

export interface Scheduled {
  segment: number // index in keep_segments
  when: number // AudioContext time the part starts
  offset: number // source seconds into the buffer
  duration: number
  fadeIn: boolean // a join: fade in over fade_ms, like the render's afade=in
  fadeOut: boolean // a join: fade out over the last fade_ms, like afade=out
}

/** Back-to-back parts from source position ``t``, the first at context time ``when``. Fades sit
 * exactly where the render puts them: in at the start of every segment but the first, out at the
 * end of every segment but the last. A part resumed mid-segment starts without a fade. */
export function schedule(keeps: Keep[], t: number, when: number): Scheduled[] {
  const from = snapToKeep(t, keeps)
  if (from === null) return []
  const first = keeps.findIndex((k) => from < k.end_s - EPS)
  const out: Scheduled[] = []
  let at = when
  for (let i = first; i < keeps.length; i++) {
    const offset = i === first ? from : keeps[i].start_s
    const duration = keeps[i].end_s - offset
    out.push({
      segment: i,
      when: at,
      offset,
      duration,
      fadeIn: i > 0 && Math.abs(offset - keeps[i].start_s) < EPS,
      fadeOut: i < keeps.length - 1,
    })
    at += duration
  }
  return out
}

/** Source position being heard at context time ``now``; null once the schedule has ended. */
export function sourceAt(parts: Scheduled[], now: number): number | null {
  for (const p of parts) {
    if (now < p.when) return p.offset
    if (now < p.when + p.duration) return p.offset + (now - p.when)
  }
  return null
}

/** Gain points for one part: [time, gain] pairs to apply with linearRampToValueAtTime. */
export function gainRamp(p: Scheduled, fadeS: number): [number, number][] {
  const fade = Math.min(fadeS, p.duration / 2)
  const pts: [number, number][] = [[p.when, p.fadeIn ? 0 : 1]]
  if (p.fadeIn) pts.push([p.when + fade, 1])
  if (p.fadeOut) pts.push([p.when + p.duration - fade, 1], [p.when + p.duration, 0])
  return pts
}

export const MIN_CUT_S = 0.02 // the API refuses shorter cuts
export const NUDGE_S = 0.01

const round3 = (x: number) => Math.round(x * 1000) / 1000

/** Move one edge by ``delta`` seconds, kept inside [0, duration] and at least 20 ms long. */
export function nudge(
  edges: { start: number; end: number },
  edge: 'start' | 'end',
  delta: number,
  duration: number,
): { start: number; end: number } {
  if (edge === 'start') {
    const start = Math.min(Math.max(0, edges.start + delta), edges.end - MIN_CUT_S)
    return { start: round3(start), end: edges.end }
  }
  const end = Math.max(Math.min(duration, edges.end + delta), edges.start + MIN_CUT_S)
  return { start: edges.start, end: round3(end) }
}

/** Alt+←/→ moves the start edge, Shift+←/→ the end edge (10 ms per press). */
export function edgeKey(e: {
  key: string
  altKey: boolean
  shiftKey: boolean
  ctrlKey?: boolean
  metaKey?: boolean
}): { edge: 'start' | 'end'; delta: number } | null {
  if (e.ctrlKey || e.metaKey || e.altKey === e.shiftKey) return null
  const dir = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : 0
  if (!dir) return null
  return { edge: e.altKey ? 'start' : 'end', delta: dir * NUDGE_S }
}

/** Min/max of the samples under each of ``width`` columns between ``from`` and ``to`` seconds. */
export function peaks(
  samples: Float32Array,
  rate: number,
  from: number,
  to: number,
  width: number,
): [number, number][] {
  const a = Math.max(0, Math.floor(from * rate))
  const b = Math.min(samples.length, Math.ceil(to * rate))
  const per = Math.max(1, (b - a) / width)
  const out: [number, number][] = []
  for (let x = 0; x < width; x++) {
    const s = Math.floor(a + x * per)
    const e = Math.min(b, Math.floor(a + (x + 1) * per))
    let lo = 0
    let hi = 0
    for (let i = s; i < e; i++) {
      const v = samples[i]
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
    out.push([lo, hi])
  }
  return out
}

/** mm:ss.cc — the 10 ms resolution of edge editing. */
export function fmtEdge(t: number): string {
  const cs = Math.round(Math.max(0, t) * 100)
  const m = Math.floor(cs / 6000)
  const s = (cs % 6000) / 100
  return `${String(m).padStart(2, '0')}:${s.toFixed(2).padStart(5, '0')}`
}

/** Where a cut really starts and ends in the plan: keep-segments snap outward to whole frames
 * and neighbouring cuts merge, so a 10 ms nudge may change nothing. null when the plan keeps the
 * middle of the cut (not approved, or too short once padded). */
export function effectiveEdges(
  edges: { start: number; end: number },
  keeps: Keep[],
  duration: number,
): { start: number; end: number } | null {
  const mid = (edges.start + edges.end) / 2
  if (keeps.some((k) => mid >= k.start_s && mid < k.end_s)) return null
  const before = keeps.filter((k) => k.end_s <= mid).pop()
  const after = keeps.find((k) => k.start_s >= mid)
  return { start: before ? before.end_s : 0, end: after ? after.start_s : duration }
}
