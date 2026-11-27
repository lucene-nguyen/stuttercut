// Saving cut edges without races (PR #13 review). The UI shows each nudge at once; the saver sends
// at most one PATCH per cut at a time and, when it returns, only the newest edges still waiting
// (latest wins). A failure is reported (the caller reloads the cuts from the API) and edits made
// after it are still sent.

export interface Edges {
  start: number
  end: number
}

export interface EdgeSaverHooks {
  send: (cutId: number, e: Edges) => Promise<{ saved_s: number }>
  onSaved: (savedS: number) => void // after each successful PATCH
  onIdle: () => void // nothing in flight or waiting for any cut: refresh the plan
  onError: (cutId: number, err: Error) => void
  delayMs?: number // debounce before a send (default 150)
}

export class EdgeSaver {
  private pending = new Map<number, Edges>()
  private inFlight = new Set<number>()
  private timers = new Map<number, ReturnType<typeof setTimeout>>()
  private hooks: EdgeSaverHooks

  constructor(hooks: EdgeSaverHooks) {
    this.hooks = hooks
  }

  /** Remember the newest edges for this cut and send them after the debounce. */
  save(cutId: number, e: Edges): void {
    this.pending.set(cutId, e)
    clearTimeout(this.timers.get(cutId))
    this.timers.set(
      cutId,
      setTimeout(() => void this.flush(cutId), this.hooks.delayMs ?? 150),
    )
  }

  get busy(): boolean {
    return this.pending.size > 0 || this.inFlight.size > 0
  }

  private async flush(cutId: number): Promise<void> {
    this.timers.delete(cutId)
    const e = this.pending.get(cutId)
    if (!e || this.inFlight.has(cutId)) return // the running PATCH sends what waits when it ends
    this.pending.delete(cutId)
    this.inFlight.add(cutId)
    try {
      this.hooks.onSaved((await this.hooks.send(cutId, e)).saved_s)
    } catch (err) {
      this.hooks.onError(cutId, err as Error)
    } finally {
      this.inFlight.delete(cutId)
    }
    if (this.pending.has(cutId)) {
      if (!this.timers.has(cutId)) await this.flush(cutId) // newer edges waited: send them now
    } else if (!this.busy) {
      this.hooks.onIdle()
    }
  }
}

/** Wraps a fetch so a response is applied only if no newer call started meanwhile. */
export function latest<T>(fetch: () => Promise<T>): () => Promise<{ fresh: boolean; value: T }> {
  let seq = 0
  return async () => {
    const mine = ++seq
    const value = await fetch()
    return { fresh: mine === seq, value }
  }
}
