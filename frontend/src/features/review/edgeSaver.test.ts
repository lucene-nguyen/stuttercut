import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { effectiveEdges } from './cleanAudio'
import { EdgeSaver, latest, type Edges } from './edgeSaver'

/** A fake API: PATCH and /plan each take some time; the "DB" holds the saved edges. */
function server(opts: {
  patchMs: (n: number) => number
  planMs: (n: number) => number
  failOn?: number
}) {
  const db = new Map<number, Edges>()
  const sent: Edges[] = []
  let patches = 0
  let plans = 0
  return {
    db,
    sent,
    send: (cutId: number, e: Edges) => {
      const n = ++patches
      sent.push(e)
      return new Promise<{ saved_s: number }>((ok, bad) =>
        setTimeout(() => {
          if (n === opts.failOn) return bad(new Error('500'))
          db.set(cutId, e)
          ok({ saved_s: e.end - e.start })
        }, opts.patchMs(n)),
      )
    },
    plan: () => {
      const n = ++plans
      const snapshot = db.get(1) // what the server would plan from, at request time
      return new Promise<Edges | undefined>((ok) => setTimeout(() => ok(snapshot), opts.planMs(n)))
    },
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('edge saver', () => {
  it('5 quick nudges: one PATCH at a time, the last value is saved, the plan matches', async () => {
    // slow first PATCH, and plan responses that come back in the wrong order
    const api = server({
      patchMs: (n) => (n === 1 ? 300 : 50),
      planMs: (n) => (n === 1 ? 400 : 20),
    })
    const getPlan = latest(api.plan)
    let shownPlan: Edges | undefined
    const refresh = async () => {
      const { fresh, value } = await getPlan()
      if (fresh) shownPlan = value
    }
    const saver = new EdgeSaver({
      send: api.send,
      onSaved: () => void refresh(),
      onIdle: () => void refresh(),
      onError: () => {},
    })

    let e = { start: 1.0, end: 1.3 }
    saver.save(1, e) // sent after the debounce
    await vi.advanceTimersByTimeAsync(160)
    for (let i = 0; i < 4; i++) {
      e = { start: +(e.start - 0.01).toFixed(2), end: e.end } // 4 more nudges while PATCH 1 runs
      saver.save(1, e)
      await vi.advanceTimersByTimeAsync(20)
    }
    await vi.advanceTimersByTimeAsync(2000)

    expect(api.db.get(1)).toEqual({ start: 0.96, end: 1.3 })
    expect(api.sent).toEqual([
      { start: 1.0, end: 1.3 },
      { start: 0.96, end: 1.3 },
    ]) // latest wins
    expect(shownPlan).toEqual({ start: 0.96, end: 1.3 }) // the stale first /plan was ignored
    expect(saver.busy).toBe(false)
  })

  it('a failed save in the middle does not drop later edits', async () => {
    const api = server({ patchMs: () => 50, planMs: () => 10, failOn: 2 })
    const errors: number[] = []
    const saver = new EdgeSaver({
      send: api.send,
      onSaved: () => {},
      onIdle: () => {},
      onError: (id) => errors.push(id),
    })
    saver.save(1, { start: 0.99, end: 1.3 })
    await vi.advanceTimersByTimeAsync(300)
    saver.save(1, { start: 0.98, end: 1.3 }) // this PATCH fails
    await vi.advanceTimersByTimeAsync(160)
    saver.save(1, { start: 0.97, end: 1.3 }) // made while it was failing
    await vi.advanceTimersByTimeAsync(1000)
    expect(errors).toEqual([1])
    expect(api.db.get(1)).toEqual({ start: 0.97, end: 1.3 })
  })

  it('keeps cuts apart and reports idle only when every cut is saved', async () => {
    const api = server({ patchMs: (n) => (n === 1 ? 200 : 20), planMs: () => 10 })
    const idle = vi.fn()
    const saver = new EdgeSaver({
      send: api.send,
      onSaved: () => {},
      onIdle: idle,
      onError: () => {},
    })
    saver.save(1, { start: 1, end: 2 })
    saver.save(2, { start: 3, end: 4 })
    await vi.advanceTimersByTimeAsync(200)
    expect(idle).not.toHaveBeenCalled() // cut 1 still in flight
    await vi.advanceTimersByTimeAsync(400)
    expect(idle).toHaveBeenCalledTimes(1)
    expect([...api.db.keys()].sort()).toEqual([1, 2])
  })
})

describe('latest', () => {
  it('marks a response stale when a newer call started', async () => {
    let n = 0
    const get = latest(
      () => new Promise<number>((ok) => setTimeout(() => ok(++n), n === 0 ? 100 : 10)),
    )
    const a = get()
    const b = get()
    await vi.advanceTimersByTimeAsync(200)
    expect((await a).fresh).toBe(false)
    expect((await b).fresh).toBe(true)
  })
})

describe('effective edges', () => {
  const keeps = [
    { start_s: 0, end_s: 1.04 },
    { start_s: 1.28, end_s: 10 },
  ]
  it('are the keep-segment ends around the cut', () => {
    expect(effectiveEdges({ start: 0.99, end: 1.3 }, keeps, 10)).toEqual({ start: 1.04, end: 1.28 })
    expect(effectiveEdges({ start: 9.5, end: 10 }, [{ start_s: 0, end_s: 9.52 }], 10)).toEqual({
      start: 9.52,
      end: 10,
    })
  })
  it('are null when the plan keeps the middle of the cut', () => {
    expect(effectiveEdges({ start: 5, end: 5.05 }, keeps, 10)).toBeNull()
  })
})
