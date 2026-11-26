import { describe, expect, it } from 'vitest'

import type { Cut, Word } from '../../api/client'
import {
  buildParagraphs,
  cutState,
  decideLocal,
  fmtDur,
  fmtStamp,
  fmtTime,
  keyAction,
  reasonStats,
  selectionRange,
  skipTarget,
  step,
  toggled,
  visibleCuts,
} from './logic'

const w = (i: number, text: string, start: number, end: number): Word => ({ i, text, start, end })
const cut = (id: number, start: number, end: number, extra: Partial<Cut> = {}): Cut => ({
  id, start_s: start, end_s: end, reason: 'filler', source: 'rules', confidence: 0.9,
  tier: 'sure', kept: 0, approved: 0, decided_at: null, llm_verdict: null, llm_reason: null,
  ...extra,
}) // prettier-ignore

const WORDS = [
  w(0, 'Xin', 0.2, 0.5),
  w(1, 'ờ', 1.0, 1.3),
  w(2, 'tôi', 2.1, 2.3),
  w(3, 'tôi', 2.35, 2.55),
  w(4, 'nói.', 2.6, 2.9),
  w(5, 'sản', 5.2, 5.5),
]

describe('time formats', () => {
  it('formats m:ss and mm:ss.s', () => {
    expect(fmtTime(168)).toBe('2:48')
    expect(fmtTime(9.6)).toBe('0:10')
    expect(fmtStamp(14.24)).toBe('00:14.2')
    expect(fmtDur(0.42)).toBe('0:00.4')
    expect(fmtDur(157.46)).toBe('2:37.5')
    expect(fmtStamp(125)).toBe('02:05.0')
  })
})

describe('cut state', () => {
  it('maps kept/approved to a state', () => {
    expect(cutState({ kept: 0, approved: 0 })).toBe('undecided')
    expect(cutState({ kept: 0, approved: 1 })).toBe('cut')
    expect(cutState({ kept: 1, approved: 0 })).toBe('kept')
  })
  it('click cycles suggestion -> cut -> kept -> cut', () => {
    expect(toggled(cut(1, 0, 1))).toBe(false)
    expect(toggled(cut(1, 0, 1, { approved: 1 }))).toBe(true)
    expect(toggled(cut(1, 0, 1, { kept: 1 }))).toBe(false)
  })
  it('decides locally', () => {
    const out = decideLocal([cut(1, 0, 1), cut(2, 1, 2)], [2], false)
    expect(out.map(cutState)).toEqual(['undecided', 'cut'])
    expect(decideLocal(out, [2], true).map(cutState)).toEqual(['undecided', 'kept'])
  })
})

describe('transcript tokens', () => {
  it('groups cut words and places a wordless pause in time', () => {
    const cuts = [
      cut(10, 1.0, 1.3),
      cut(11, 2.1, 2.3, { reason: 'repeat' }),
      cut(12, 3.0, 5.0, { reason: 'pause' }),
    ]
    const tokens = buildParagraphs(WORDS, cuts).flatMap((p) => p.tokens)
    expect(tokens.map((t) => (t.kind === 'cut' ? `[${t.text}]` : t.text))).toEqual([
      'Xin', '[ờ]', '[tôi]', 'tôi', 'nói.', '[· 2.0s ·]', 'sản',
    ]) // prettier-ignore
  })
  it('merges consecutive words of one cut and starts paragraphs', () => {
    const paras = buildParagraphs(WORDS, [cut(1, 2.1, 2.9, { reason: 'retake' })], 3)
    expect(paras.length).toBeGreaterThan(1)
    const c = paras.flatMap((p) => p.tokens).find((t) => t.kind === 'cut')
    expect(c && c.kind === 'cut' && [c.text, c.first, c.last]).toEqual(['tôi tôi nói.', 2, 4])
    expect(paras[0].time).toBe(0.2)
  })
})

describe('navigation and filter', () => {
  const cuts = [cut(1, 5, 6, { reason: 'pause' }), cut(2, 1, 2), cut(3, 3, 4, { reason: 'repeat' })]
  it('orders by time and filters by reason', () => {
    expect(visibleCuts(cuts, 'all').map((c) => c.id)).toEqual([2, 3, 1])
    expect(visibleCuts(cuts, 'repeat').map((c) => c.id)).toEqual([3])
  })
  it('steps within range', () => {
    expect(step(3, -1, 1)).toBe(0)
    expect(step(3, -1, -1)).toBe(2)
    expect(step(3, 2, 1)).toBe(2)
    expect(step(3, 0, -1)).toBe(0)
    expect(step(0, -1, 1)).toBe(-1)
  })
})

describe('keyboard', () => {
  const div = { tagName: 'DIV' } as unknown as EventTarget
  it('maps review keys', () => {
    expect(['k', 'X', ' ', 'ArrowLeft', 'ArrowRight', 'Enter', 'q'].map((k) => keyAction(k, div))).toEqual([
      'keep', 'cut', 'play', 'prev', 'next', 'render', null,
    ]) // prettier-ignore
  })
  it('ignores keys while typing, and Space on a button', () => {
    expect(keyAction('k', { tagName: 'INPUT' } as unknown as EventTarget)).toBeNull()
    expect(keyAction(' ', { tagName: 'BUTTON' } as unknown as EventTarget)).toBeNull()
  })
})

describe('preview skip and stats', () => {
  const cuts = [cut(1, 1, 2, { approved: 1 }), cut(2, 2, 3, { approved: 1 }), cut(3, 5, 6)]
  it('jumps over approved cuts only, chaining touching ones', () => {
    expect(skipTarget(1.5, cuts)).toBe(3)
    expect(skipTarget(5.5, cuts)).toBeNull() // undecided: still played
    expect(skipTarget(0.5, cuts)).toBeNull()
  })
  it('counts active cuts and saved seconds per reason', () => {
    const filler = reasonStats(cuts).find((s) => s.reason === 'filler')
    expect(filler).toEqual({ reason: 'filler', total: 3, active: 2, savedS: 2 })
  })
  it('turns a selection into a time range in either direction', () => {
    expect(selectionRange(WORDS, 3, 2)).toEqual({ start: 2.1, end: 2.55 })
    expect(selectionRange(WORDS, 0, 99)).toBeNull()
  })
})
