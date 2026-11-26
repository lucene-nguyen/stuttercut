// Pure review logic (no React): transcript tokens, cut states, filtering, keyboard, preview skip.
import type { Cut, Reason, Word } from '../../api/client'

export const REASONS: Reason[] = ['filler', 'repeat', 'pause', 'retake']

export const REASON_META: Record<Reason, { label: string; color: string; bg: string }> = {
  filler: { label: 'Filler', color: '#F2B544', bg: 'rgba(242,181,68,0.16)' },
  repeat: { label: 'Repeat', color: '#FF8A66', bg: 'rgba(255,138,102,0.16)' },
  pause: { label: 'Pause', color: '#4FD1C5', bg: 'rgba(79,209,197,0.14)' },
  retake: { label: 'Retake', color: '#C4A3FF', bg: 'rgba(196,163,255,0.16)' },
}

/** cut = approved for render; kept = the user restored it; undecided = only a suggestion. */
export type CutState = 'cut' | 'kept' | 'undecided'

export function cutState(c: Pick<Cut, 'kept' | 'approved'>): CutState {
  if (c.kept) return 'kept'
  return c.approved ? 'cut' : 'undecided'
}

/** m:ss, e.g. 2:48 */
export function fmtTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** m:ss.s, e.g. 2:37.4: savings of under a second still show */
export function fmtDur(seconds: number): string {
  const t = Math.max(0, Math.round(seconds * 10) / 10)
  const m = Math.floor(t / 60)
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, '0')}`
}

/** mm:ss.s, e.g. 00:14.2 */
export function fmtStamp(seconds: number): string {
  const t = Math.max(0, seconds)
  const m = Math.floor(t / 60)
  return `${String(m).padStart(2, '0')}:${(t - m * 60).toFixed(1).padStart(4, '0')}`
}

export type Token =
  | { kind: 'word'; text: string; i: number; start: number; end: number }
  | {
      kind: 'cut'
      cutId: number
      text: string
      first: number | null
      last: number | null
      start: number
      end: number
    }

export interface Paragraph {
  time: number
  tokens: Token[]
}

const EPS = 0.01

/** Words grouped into paragraphs; the words of a cut become one token, a cut with no words
 * (a pause) becomes a "· 1.2s ·" token where it sits in time. */
export function buildParagraphs(words: Word[], cuts: Cut[], maxWords = 28): Paragraph[] {
  const sorted = [...cuts].sort((a, b) => a.start_s - b.start_s)
  const owner = new Map<number, Cut>()
  for (const c of sorted) {
    for (const w of words) {
      if (w.start >= c.start_s - EPS && w.end <= c.end_s + EPS && !owner.has(w.i)) owner.set(w.i, c)
    }
  }
  const wordless = sorted.filter((c) => !words.some((w) => owner.get(w.i) === c))
  const tokens: Token[] = []
  let gapIdx = 0
  const flushWordless = (before: number) => {
    while (gapIdx < wordless.length && wordless[gapIdx].start_s < before) {
      const c = wordless[gapIdx++]
      tokens.push({ kind: 'cut', cutId: c.id, text: `· ${(c.end_s - c.start_s).toFixed(1)}s ·`,
        first: null, last: null, start: c.start_s, end: c.end_s }) // prettier-ignore
    }
  }
  for (const w of words) {
    flushWordless(w.start)
    const c = owner.get(w.i)
    const prev = tokens[tokens.length - 1]
    if (c && prev?.kind === 'cut' && prev.cutId === c.id) {
      prev.text += ` ${w.text}`
      prev.last = w.i
    } else if (c) {
      tokens.push({
        kind: 'cut',
        cutId: c.id,
        text: w.text,
        first: w.i,
        last: w.i,
        start: c.start_s,
        end: c.end_s,
      })
    } else {
      tokens.push({ kind: 'word', text: w.text, i: w.i, start: w.start, end: w.end })
    }
  }
  flushWordless(Infinity)

  const paras: Paragraph[] = []
  let count = 0
  for (const t of tokens) {
    const last = paras[paras.length - 1]
    const lastTok = last?.tokens[last.tokens.length - 1]
    const sentenceEnd = lastTok?.kind === 'word' && /[.?!]$/.test(lastTok.text)
    if (!last || count >= maxWords || (sentenceEnd && count >= 8)) {
      paras.push({ time: t.start, tokens: [t] })
      count = 1
    } else {
      last.tokens.push(t)
      count++
    }
  }
  return paras
}

/** Cuts in time order, optionally one reason only. */
export function visibleCuts(cuts: Cut[], filter: Reason | 'all'): Cut[] {
  return [...cuts]
    .filter((c) => filter === 'all' || c.reason === filter)
    .sort((a, b) => a.start_s - b.start_s)
}

/** Index after moving ``dir`` from ``current`` (-1 = none selected); stays in range. */
export function step(length: number, current: number, dir: 1 | -1): number {
  if (length === 0) return -1
  if (current < 0) return dir === 1 ? 0 : length - 1
  return Math.min(length - 1, Math.max(0, current + dir))
}

export type KeyAction = 'play' | 'keep' | 'cut' | 'prev' | 'next' | 'render'

const KEYS: Record<string, KeyAction> = {
  ' ': 'play', k: 'keep', K: 'keep', x: 'cut', X: 'cut',
  ArrowLeft: 'prev', ArrowRight: 'next', Enter: 'render',
} // prettier-ignore

/** Review shortcut for a key press, unless the user is typing in a field. */
export function keyAction(key: string, target: EventTarget | null): KeyAction | null {
  const el = target as HTMLElement | null
  const tag = el?.tagName ?? ''
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable)
    return null
  if (key === ' ' && tag === 'BUTTON') return null // Space on a button presses the button
  return KEYS[key] ?? null
}

/** Preview of the clean version: inside an approved cut, jump to its end. */
export function skipTarget(t: number, cuts: Cut[]): number | null {
  let target: number | null = null
  let pos = t
  for (const c of [...cuts].sort((a, b) => a.start_s - b.start_s)) {
    if (cutState(c) === 'cut' && pos >= c.start_s - EPS && pos < c.end_s - EPS) {
      pos = c.end_s
      target = pos
    }
  }
  return target
}

export interface ReasonStats {
  reason: Reason
  total: number
  active: number
  savedS: number
}

export function reasonStats(cuts: Cut[]): ReasonStats[] {
  return REASONS.map((reason) => {
    const mine = cuts.filter((c) => c.reason === reason)
    const active = mine.filter((c) => cutState(c) === 'cut')
    return {
      reason,
      total: mine.length,
      active: active.length,
      savedS: active.reduce((s, c) => s + (c.end_s - c.start_s), 0),
    }
  })
}

/** The time range of a transcript selection between two word indices (either order). */
export function selectionRange(
  words: Word[],
  a: number,
  b: number,
): { start: number; end: number } | null {
  const [first, last] = a <= b ? [a, b] : [b, a]
  if (!words[first] || !words[last]) return null
  return { start: words[first].start, end: words[last].end }
}

/** Apply a decision locally (optimistic update before the API answers). */
export function decideLocal(cuts: Cut[], ids: number[], keep: boolean): Cut[] {
  const set = new Set(ids)
  return cuts.map((c) => (set.has(c.id) ? { ...c, kept: keep ? 1 : 0, approved: keep ? 0 : 1 } : c))
}

/** Clicking a cut: suggestion -> cut -> kept -> cut ... */
export function toggled(c: Cut): boolean {
  return cutState(c) === 'cut' // true = keep it now
}
