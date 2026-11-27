import { describe, expect, it } from 'vitest'

import {
  cleanLength,
  edgeKey,
  fmtEdge,
  gainRamp,
  nudge,
  peaks,
  schedule,
  snapToKeep,
  sourceAt,
  toClean,
  toSource,
  type Keep,
} from './cleanAudio'

const k = (start_s: number, end_s: number): Keep => ({ start_s, end_s })
// cuts at 1.04-1.24 and 2.0-3.0 (chained with nothing kept in between would merge in the plan)
const KEEPS = [k(0, 1.04), k(1.24, 2.0), k(3.0, 10.0)]

describe('time mapping', () => {
  it('maps source to clean and back on kept parts', () => {
    expect(toClean(0.5, KEEPS)).toBeCloseTo(0.5)
    expect(toClean(1.5, KEEPS)).toBeCloseTo(1.04 + 0.26)
    expect(toClean(5, KEEPS)).toBeCloseTo(1.04 + 0.76 + 2)
    expect(toSource(toClean(5, KEEPS), KEEPS)).toBeCloseTo(5)
    expect(toSource(1.04 + 0.1, KEEPS)).toBeCloseTo(1.34)
    expect(cleanLength(KEEPS)).toBeCloseTo(8.8)
  })
  it('puts a time inside a cut at the next segment', () => {
    expect(toClean(1.1, KEEPS)).toBeCloseTo(1.04)
    expect(snapToKeep(1.1, KEEPS)).toBe(1.24)
    expect(snapToKeep(2.5, KEEPS)).toBe(3.0)
    expect(snapToKeep(0.3, KEEPS)).toBe(0.3)
    expect(snapToKeep(10, KEEPS)).toBeNull()
  })
})

describe('schedule', () => {
  it('plays the segments back to back with fades only at joins', () => {
    const parts = schedule(KEEPS, 0, 100)
    expect(
      parts.map((p) => [p.segment, +p.when.toFixed(3), p.offset, +p.duration.toFixed(3)]),
    ).toEqual([
      [0, 100, 0, 1.04],
      [1, 101.04, 1.24, 0.76],
      [2, 101.8, 3.0, 7],
    ])
    expect(parts.map((p) => [p.fadeIn, p.fadeOut])).toEqual([
      [false, true],
      [true, true],
      [true, false],
    ])
  })
  it('starts at the next segment when the position is inside a cut', () => {
    const parts = schedule(KEEPS, 2.5, 0)
    expect(parts).toHaveLength(1)
    expect(parts[0]).toMatchObject({ segment: 2, offset: 3.0, fadeIn: true })
  })
  it('resumes mid-segment without a fade-in', () => {
    const [first] = schedule(KEEPS, 1.5, 0)
    expect(first).toMatchObject({ segment: 1, offset: 1.5, fadeIn: false, fadeOut: true })
    expect(first.duration).toBeCloseTo(0.5)
  })
  it('reschedules from the current position after an edit changes the plan', () => {
    const before = schedule(KEEPS, 0, 0)
    const heard = sourceAt(before, 1.5)! // in segment 1, source 1.24 + 0.46
    expect(heard).toBeCloseTo(1.7)
    const edited = [k(0, 1.04), k(1.24, 1.8), k(3.0, 10.0)] // the next cut now starts at 1.8
    const after = schedule(edited, heard, 50)
    expect(after[0]).toMatchObject({ segment: 1, when: 50, offset: heard })
    expect(after[0].duration).toBeCloseTo(0.1)
    expect(after[1].when).toBeCloseTo(50.1)
  })
  it('is empty after the end and tracks the heard position', () => {
    expect(schedule(KEEPS, 10, 0)).toEqual([])
    const parts = schedule(KEEPS, 0, 0)
    expect(sourceAt(parts, 1.1)).toBeCloseTo(1.3)
    expect(sourceAt(parts, 99)).toBeNull()
  })
  it('ramps the gain over the fade at each join', () => {
    const [, mid] = schedule(KEEPS, 0, 0)
    expect(gainRamp(mid, 0.01).map(([t, g]) => [+t.toFixed(3), g])).toEqual([
      [1.04, 0],
      [1.05, 1],
      [1.79, 1],
      [1.8, 0],
    ])
    expect(gainRamp(schedule(KEEPS, 0, 0)[0], 0.01)[0]).toEqual([0, 1]) // clip start: no fade
  })
})

describe('edge nudging', () => {
  it('moves one edge 10 ms and keeps the cut inside the clip and at least 20 ms', () => {
    expect(nudge({ start: 1.0, end: 1.3 }, 'start', -0.01, 10)).toEqual({ start: 0.99, end: 1.3 })
    expect(nudge({ start: 1.0, end: 1.3 }, 'end', 0.01, 10)).toEqual({ start: 1.0, end: 1.31 })
    expect(nudge({ start: 0.005, end: 1 }, 'start', -0.01, 10).start).toBe(0)
    expect(nudge({ start: 9, end: 9.995 }, 'end', 0.01, 10).end).toBe(10)
    expect(nudge({ start: 1.0, end: 1.025 }, 'start', 0.01, 10)).toEqual({
      start: 1.005,
      end: 1.025,
    })
    expect(nudge({ start: 1.0, end: 1.02 }, 'end', -0.01, 10)).toEqual({ start: 1.0, end: 1.02 })
  })
  it('maps Alt / Shift + arrows to the start / end edge', () => {
    expect(edgeKey({ key: 'ArrowLeft', altKey: true, shiftKey: false })).toEqual({
      edge: 'start',
      delta: -0.01,
    })
    expect(edgeKey({ key: 'ArrowRight', altKey: false, shiftKey: true })).toEqual({
      edge: 'end',
      delta: 0.01,
    })
    expect(edgeKey({ key: 'ArrowRight', altKey: false, shiftKey: false })).toBeNull() // plain → stays "next cut"
    expect(edgeKey({ key: 'ArrowRight', altKey: true, shiftKey: true })).toBeNull()
    expect(edgeKey({ key: 'ArrowRight', altKey: true, shiftKey: false, metaKey: true })).toBeNull()
    expect(edgeKey({ key: 'k', altKey: true, shiftKey: false })).toBeNull()
  })
})

describe('edge times', () => {
  it('shows edges to 10 ms', () => {
    expect(fmtEdge(51.234)).toBe('00:51.23')
    expect(fmtEdge(61.005)).toBe('01:01.01')
    expect(fmtEdge(0)).toBe('00:00.00')
  })
})

describe('waveform peaks', () => {
  it('takes min and max per column', () => {
    const s = new Float32Array([0, 0.5, -0.25, 0.125, -1, 0.25, 0, 0])
    expect(peaks(s, 4, 0, 2, 2)).toEqual([
      [-0.25, 0.5],
      [-1, 0.25],
    ])
    expect(peaks(s, 4, 1.5, 9, 1)).toEqual([[0, 0]])
  })
})
