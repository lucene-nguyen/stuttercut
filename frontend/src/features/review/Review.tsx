import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  api,
  watchJob,
  type Cut,
  type JobDetail,
  type JobSummary,
  type Reason,
  type RenderFormat,
} from '../../api/client'
import { revealLabel } from '../../components/reveal'
import {
  REASONS,
  REASON_META,
  buildParagraphs,
  cutState,
  decideLocal,
  fmtStamp,
  fmtDur,
  fmtTime,
  keyAction,
  reasonStats,
  selectionRange,
  step,
  toggled,
  visibleCuts,
  type CutState,
} from './logic'
import { cleanLength, edgeKey, nudge, toClean } from './cleanAudio'
import EdgeEditor from './EdgeEditor'
import { useCleanPlayer } from './useCleanPlayer'

const STATE_TEXT: Record<CutState, string> = {
  cut: 'will be cut',
  kept: 'kept',
  undecided: 'suggested, not cut yet',
}

const FORMATS: { key: RenderFormat; label: string; sub: string }[] = [
  { key: 'mp4', label: 'MP4 video', sub: 'H.264, hardware encode when available' },
  { key: 'xml', label: 'Editor timeline', sub: 'FCP XML, no re-encode' },
  { key: 'both', label: 'Both', sub: '' },
]

function tokenStyle(c: Cut, dim: boolean): React.CSSProperties {
  const m = REASON_META[c.reason]
  const st = cutState(c)
  return {
    background: st === 'kept' ? 'transparent' : m.bg,
    color: st === 'kept' ? undefined : m.color,
    borderColor: st === 'cut' ? 'transparent' : m.color,
    borderStyle: st === 'kept' ? 'dashed' : st === 'undecided' ? 'dotted' : 'solid',
    opacity: dim ? 0.4 : 1,
  }
}

/** Word index range of the current text selection inside the transcript, if any. */
function readSelection(root: HTMLElement | null): [number, number] | null {
  const sel = window.getSelection()
  if (!root || !sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const idx = (node: Node | null, edge: 'first' | 'last'): number | null => {
    const el = (node instanceof HTMLElement ? node : node?.parentElement)?.closest<HTMLElement>(
      '[data-i],[data-first]',
    )
    if (!el || !root.contains(el)) return null
    const v = el.dataset.i ?? (edge === 'first' ? el.dataset.first : el.dataset.last)
    return v === undefined ? null : Number(v)
  }
  const a = idx(sel.anchorNode, 'first')
  const b = idx(sel.focusNode, 'last')
  return a === null || b === null ? null : [Math.min(a, b), Math.max(a, b)]
}

export default function Review({ id, platform }: { id: string; platform: string }) {
  const [job, setJob] = useState<JobDetail | null>(null)
  const [cuts, setCuts] = useState<Cut[]>([])
  const [savedS, setSavedS] = useState(0)
  const [filter, setFilter] = useState<Reason | 'all'>('all')
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [now, setNow] = useState(0)
  const [cleanMode, setCleanMode] = useState(true)
  const [renderOpen, setRenderOpen] = useState(false)
  const [fmt, setFmt] = useState<RenderFormat>('mp4')
  const [folder, setFolder] = useState('')
  const [render, setRender] = useState<{
    state: 'idle' | 'running' | 'done' | 'failed'
    percent?: number | null
    result?: JobSummary
    tookS?: number
  }>({ state: 'idle' })
  const [sel, setSel] = useState<[number, number] | null>(null)
  const [missedReason, setMissedReason] = useState<Reason>('filler')
  const video = useRef<HTMLVideoElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const stopWatch = useRef<(() => void) | null>(null)
  const player = useCleanPlayer(id, video)
  const { reloadPlan } = player

  const load = useCallback(() => {
    api.getJob(id).then(
      (j) => {
        setJob(j)
        setCuts(j.cuts)
        setSavedS(j.saved_s)
        void reloadPlan().catch(() => undefined) // the clean preview follows every change
      },
      (e: Error) => setError(e.message),
    )
  }, [id, reloadPlan])
  useEffect(() => {
    load()
    return () => stopWatch.current?.()
  }, [load])

  const words = useMemo(() => job?.words ?? [], [job])
  const paragraphs = useMemo(() => buildParagraphs(words, cuts), [words, cuts])
  const visible = useMemo(() => visibleCuts(cuts, filter), [cuts, filter])
  const stats = useMemo(() => reasonStats(cuts), [cuts])
  const duration = job?.duration_s ?? 0
  const active = cuts.filter((c) => cutState(c) === 'cut').length
  const selectedCut = cuts.find((c) => c.id === selected) ?? null

  const decide = useCallback(
    async (ids: number[], keep: boolean) => {
      if (ids.length === 0) return
      const before = cuts
      setCuts((cs) => decideLocal(cs, ids, keep))
      try {
        let saved = savedS
        for (const cutId of ids) saved = (await api.decide(id, cutId, keep)).saved_s
        setSavedS(saved)
        setError('')
        void reloadPlan()
      } catch (e) {
        setCuts(before)
        setError(`Not saved: ${(e as Error).message}`)
      }
    },
    [cuts, id, reloadPlan, savedS],
  )

  /** Move a cut's edges (drag, nudge, Alt/Shift+arrows, Reset); this also approves the cut. */
  const setEdges = useCallback(
    async (cutId: number, start: number, end: number) => {
      const before = cuts
      setCuts((cs) =>
        cs.map((c) =>
          c.id === cutId
            ? { ...c, start_s: start, end_s: end, approved: 1, kept: 0,
                start_edited: Math.abs(start - c.orig_start_s) > 1e-6 ? 1 : 0,
                end_edited: Math.abs(end - c.orig_end_s) > 1e-6 ? 1 : 0 } // prettier-ignore
            : c,
        ),
      )
      try {
        setSavedS((await api.setEdges(id, cutId, start, end)).saved_s)
        setError('')
        await reloadPlan()
      } catch (e) {
        setCuts(before)
        setError(`Edges not saved: ${(e as Error).message}`)
      }
    },
    [cuts, id, reloadPlan],
  )

  async function bulk(action: 'approve_sure' | 'cut_all' | 'keep_all') {
    try {
      const res = await api.bulk(id, action)
      setSavedS(res.saved_s)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const { seek, loadAudio } = player
  const select = useCallback(
    (c: Cut | undefined) => {
      if (!c) return
      setSelected(c.id)
      const t = Math.max(0, c.start_s - 0.3)
      if (cleanMode) seek(t)
      else if (video.current) video.current.currentTime = t
      void loadAudio() // the edge editor's waveform
      document.getElementById(`cut-${c.id}`)?.scrollIntoView({ block: 'nearest' })
    },
    [cleanMode, loadAudio, seek],
  )

  const startRender = useCallback(async () => {
    setError('')
    const t0 = performance.now()
    try {
      await api.render(id, fmt, folder)
    } catch (e) {
      setError((e as Error).message)
      return
    }
    setRender({ state: 'running', percent: 0 })
    stopWatch.current = watchJob(
      id,
      (p) => setRender((r) => ({ ...r, percent: p.percent })),
      (result) =>
        setRender(
          result.status === 'done'
            ? { state: 'done', result, tookS: (performance.now() - t0) / 1000 }
            : { state: 'failed', result },
        ),
    )
  }, [fmt, folder, id])

  // Keyboard: Space play, K keep, X cut, ←/→ previous/next cut, Enter render.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const ek = edgeKey(e)
      if (ek) {
        // keyAction answers null while typing in a field: then the arrows belong to the field
        if (!selectedCut || !keyAction(e.key, e.target)) return
        e.preventDefault()
        const n = nudge(
          { start: selectedCut.start_s, end: selectedCut.end_s },
          ek.edge,
          ek.delta,
          duration,
        )
        void setEdges(selectedCut.id, n.start, n.end)
        return
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const action = keyAction(e.key, e.target)
      if (!action) return
      e.preventDefault()
      const pos = visible.findIndex((c) => c.id === selected)
      if (action === 'play' && cleanMode) {
        if (player.playing) player.pause()
        else void player.play()
      } else if (action === 'play' && video.current) {
        if (video.current.paused) void video.current.play()
        else video.current.pause()
      } else if (action === 'prev' || action === 'next') {
        select(visible[step(visible.length, pos, action === 'next' ? 1 : -1)])
      } else if ((action === 'keep' || action === 'cut') && selectedCut) {
        void decide([selectedCut.id], action === 'keep')
      } else if (action === 'render') {
        if (renderOpen && render.state === 'idle') void startRender()
        else setRenderOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    cleanMode,
    decide,
    duration,
    player,
    render.state,
    renderOpen,
    select,
    selected,
    selectedCut,
    setEdges,
    startRender,
    visible,
  ])

  function toggleClean(on: boolean) {
    player.pause()
    video.current?.pause()
    if (video.current) video.current.muted = on
    setCleanMode(on)
  }

  async function markMissed() {
    if (!sel) return
    const range = selectionRange(words, sel[0], sel[1])
    if (!range) return
    try {
      const res = await api.addCut(id, range.start, range.end, missedReason)
      setSavedS(res.saved_s)
      setSel(null)
      window.getSelection()?.removeAllRanges()
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!job) {
    return (
      <main className="page">
        <a href="#/">← Projects</a>
        {error ? (
          <div role="alert" className="alert">
            {error}
          </div>
        ) : (
          <p className="muted">Loading…</p>
        )}
      </main>
    )
  }

  const clean = duration - savedS
  const selText = sel
    ? words
        .slice(sel[0], sel[1] + 1)
        .map((w) => w.text)
        .join(' ')
    : ''
  const groups: [string, Cut[]][] = [
    ['Sure', visible.filter((c) => c.tier === 'sure')],
    ['Unsure', visible.filter((c) => c.tier === 'unsure')],
  ]

  return (
    <>
      <header className="review-head">
        <div className="row" style={{ gap: 16 }}>
          <a href="#/" className="btn" style={{ border: 'none', color: 'var(--muted)' }}>
            ← Projects
          </a>
          <h1 style={{ fontSize: 18 }}>{job.name}</h1>
          <div className="stats" aria-live="polite">
            <span>
              Original <b>{fmtTime(duration)}</b>
            </span>
            <span>
              Clean{' '}
              <b className="good" data-testid="clean">
                {fmtDur(clean)}
              </b>
            </span>
            <span>
              Saved{' '}
              <b className="good" data-testid="saved">
                −{fmtDur(savedS)}
              </b>
            </span>
            <span>
              Cuts{' '}
              <b data-testid="cut-count">
                {active}/{cuts.length}
              </b>
            </span>
          </div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => void bulk('approve_sure')}>
            Approve all sure
          </button>
          <button className="btn" onClick={() => void bulk('keep_all')}>
            Keep all words
          </button>
          <button className="btn" onClick={() => void bulk('cut_all')}>
            Cut all suggested
          </button>
          <button
            className="btn primary"
            aria-expanded={renderOpen}
            onClick={() => setRenderOpen((o) => !o)}
          >
            Approve &amp; render
          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="alert" style={{ margin: '16px 32px 0' }}>
          {error}
        </div>
      )}

      {renderOpen && (
        <section className="render-panel" aria-labelledby="render-title">
          {render.state === 'done' && render.result ? (
            <div role="status" className="row spread">
              <div>
                <div style={{ fontWeight: 500 }}>Rendered in {fmtTime(render.tookS ?? 0)}</div>
                <div className="mono" style={{ fontSize: 13, color: '#A6E9D1' }}>
                  {[render.result.output_path, render.result.xml_path]
                    .filter(Boolean)
                    .map((p) => p!.split(/[\\/]/).pop())
                    .join(' + ')}{' '}
                  · {fmtDur(clean)}
                </div>
              </div>
              <div className="row">
                <button
                  className="btn"
                  onClick={() => void api.reveal(id).catch((e: Error) => setError(e.message))}
                >
                  {revealLabel(platform)}
                </button>
                <a className="btn primary" href="#/">
                  Next video
                </a>
              </div>
            </div>
          ) : (
            <div className="row" style={{ alignItems: 'flex-end', gap: 16 }}>
              <fieldset className="formats">
                <legend
                  id="render-title"
                  style={{ fontSize: 16, fontWeight: 600, paddingBottom: 8 }}
                >
                  Render as
                </legend>
                {FORMATS.map((f) => (
                  <label key={f.key}>
                    <input
                      type="radio"
                      name="fmt"
                      checked={fmt === f.key}
                      onChange={() => setFmt(f.key)}
                    />
                    <span>
                      <span style={{ fontWeight: 500 }}>{f.label}</span>{' '}
                      {f.sub && (
                        <span className="muted" style={{ fontSize: 13 }}>
                          · {f.sub}
                        </span>
                      )}
                    </span>
                  </label>
                ))}
              </fieldset>
              <label
                className="muted"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  fontSize: 13,
                  flex: '1 1 220px',
                }}
              >
                Save to
                <input
                  className="field mono"
                  style={{ minHeight: 44 }}
                  value={folder}
                  placeholder="Default: Videos/StutterCut"
                  onChange={(e) => setFolder(e.target.value)}
                />
              </label>
              <div className="row">
                <button
                  className="btn"
                  onClick={() => setRenderOpen(false)}
                  disabled={render.state === 'running'}
                >
                  Cancel
                </button>
                <button
                  className="btn primary"
                  onClick={() => void startRender()}
                  disabled={render.state === 'running'}
                >
                  {render.state === 'running'
                    ? `Rendering${render.percent != null ? ` · ${render.percent}%` : '…'}`
                    : `Render ${fmtDur(clean)} video`}
                </button>
              </div>
              {render.state === 'failed' && (
                <div role="alert" className="alert" style={{ flexBasis: '100%' }}>
                  Render failed: {render.result?.error}. Your cuts are saved; try again or open the
                  trace in <a href={`#/diagnostics?job=${id}`}>Diagnostics</a>.
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <main className="review-main">
        <section aria-label="Preview" className="col-left">
          <video
            ref={video}
            src={api.previewUrl(id)}
            controls={!cleanMode}
            muted={cleanMode}
            playsInline
            preload="metadata"
            onTimeUpdate={(e) => !cleanMode && setNow(e.currentTarget.currentTime)}
            aria-label="Preview of the video"
          />
          <label className="row muted" style={{ fontSize: 13 }}>
            <input
              type="checkbox"
              checked={cleanMode}
              onChange={(e) => toggleClean(e.target.checked)}
            />
            Play the clean version (exactly what the render keeps)
          </label>
          {cleanMode && (
            <div className="row clean-controls">
              <button
                className="btn small primary"
                onClick={() => (player.playing ? player.pause() : void player.play())}
              >
                {player.loading
                  ? 'Loading audio…'
                  : player.playing
                    ? 'Pause clean preview'
                    : 'Play clean preview'}
              </button>
              <input
                type="range"
                min={0}
                max={duration || 0}
                step={0.01}
                value={player.position}
                onChange={(e) => player.seek(Number(e.target.value))}
                aria-label="Seek in the clean preview (source time)"
                style={{ flex: 1 }}
              />
              <span className="mono muted" style={{ fontSize: 13 }} data-testid="clean-clock">
                {fmtDur(toClean(player.position, player.plan?.keep_segments ?? []))} /{' '}
                {fmtDur(cleanLength(player.plan?.keep_segments ?? []))}
              </span>
            </div>
          )}
          {player.error && (
            <div role="alert" className="alert">
              {player.error}
            </div>
          )}
          <div>
            <div className="row spread mono muted" style={{ fontSize: 13 }}>
              <span>{fmtStamp(cleanMode ? player.position : now)}</span>
              <span>{fmtStamp(duration)}</span>
            </div>
            <div className="timeline" role="group" aria-label="Timeline with cut markers">
              {cuts.map((c) => {
                const st = cutState(c)
                const dim = filter !== 'all' && c.reason !== filter
                return (
                  <button
                    key={c.id}
                    style={{
                      left: `${(c.start_s / (duration || 1)) * 100}%`,
                      width: `${((c.end_s - c.start_s) / (duration || 1)) * 100}%`,
                      background: st === 'kept' ? 'var(--line-2)' : REASON_META[c.reason].color,
                      opacity: dim ? 0.3 : st === 'undecided' ? 0.55 : 1,
                    }}
                    aria-label={`${REASON_META[c.reason].label} at ${fmtStamp(c.start_s)}, ${STATE_TEXT[st]}`}
                    onClick={() => select(c)}
                  />
                )
              })}
              <div
                className="playhead"
                style={{
                  left: `${((cleanMode ? player.position : now) / (duration || 1)) * 100}%`,
                }}
              />
            </div>
          </div>
          {selectedCut && (
            <EdgeEditor
              cut={selectedCut}
              duration={duration}
              audio={player.audio}
              loading={player.loading}
              onEdges={(s0, e0) => void setEdges(selectedCut.id, s0, e0)}
              onPlayAround={(t) => void player.playAround(t)}
            />
          )}
          <div className="kinds">
            {stats.map((s) => (
              <div key={s.reason} className="kind">
                <span>
                  <span className="swatch" style={{ background: REASON_META[s.reason].color }} />
                  {REASON_META[s.reason].label}
                </span>
                <span className="mono muted" style={{ fontSize: 13 }}>
                  {s.active}/{s.total} · −{s.savedS.toFixed(1)}s
                </span>
              </div>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            Keys: <kbd>Space</kbd> play · <kbd>←</kbd>/<kbd>→</kbd> previous/next cut · <kbd>K</kbd>{' '}
            keep · <kbd>X</kbd> cut · <kbd>Enter</kbd> render · <kbd>Alt</kbd>+<kbd>←</kbd>/
            <kbd>→</kbd> start edge · <kbd>Shift</kbd>+<kbd>←</kbd>/<kbd>→</kbd> end edge (10 ms)
          </p>
        </section>

        <section aria-labelledby="tr" className="col-right">
          <div className="row spread">
            <h2 id="tr">Transcript</h2>
            <div role="group" aria-label="Filter by reason" className="row" style={{ gap: 6 }}>
              {(['all', ...REASONS] as const).map((r) => (
                <button
                  key={r}
                  className="chip"
                  aria-pressed={filter === r}
                  onClick={() => setFilter(r)}
                >
                  {r === 'all' ? 'All' : REASON_META[r].label}{' '}
                  {r === 'all' ? cuts.length : cuts.filter((c) => c.reason === r).length}
                </button>
              ))}
            </div>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>
            Struck-through words will be cut; dotted ones are suggestions that stay until you cut
            them. Click a word to cut or keep it. Select words to mark a cut the detector missed.
          </p>
          <div className="row card" style={{ padding: '8px 12px', minHeight: 56 }}>
            {sel ? (
              <>
                <span style={{ flex: 1, minWidth: 0 }}>
                  Selected: <span lang="vi">“{selText}”</span>
                </span>
                <label className="row muted" style={{ fontSize: 13 }}>
                  Reason
                  <select
                    className="field"
                    value={missedReason}
                    onChange={(e) => setMissedReason(e.target.value as Reason)}
                  >
                    {REASONS.map((r) => (
                      <option key={r} value={r}>
                        {REASON_META[r].label}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="btn small primary" onClick={() => void markMissed()}>
                  Mark missed cut
                </button>
              </>
            ) : (
              <span className="muted" style={{ fontSize: 13 }}>
                Select words in the transcript to mark a missed cut.
              </span>
            )}
          </div>
          <div
            className="transcript"
            ref={transcript}
            lang="vi"
            onMouseUp={() => setSel(readSelection(transcript.current))}
            onKeyUp={() => setSel(readSelection(transcript.current))}
          >
            {paragraphs.map((p, n) => (
              <div className="para" key={n}>
                <time>{fmtStamp(p.time).slice(0, 5)}</time>
                <div className="words">
                  {p.tokens.map((t) => {
                    if (t.kind === 'word')
                      return (
                        <span key={`w${t.i}`} data-i={t.i}>
                          {t.text}{' '}
                        </span>
                      )
                    const c = cuts.find((x) => x.id === t.cutId)!
                    const st = cutState(c)
                    const dim = filter !== 'all' && c.reason !== filter
                    return (
                      <span key={`c${t.cutId}`}>
                        <button
                          id={`cut-${c.id}`}
                          className={`tok ${st}${selected === c.id ? ' selected' : ''}`}
                          style={tokenStyle(c, dim)}
                          data-first={t.first ?? undefined}
                          data-last={t.last ?? undefined}
                          aria-pressed={st === 'cut'}
                          title={`${REASON_META[c.reason].label} · ${c.tier} · ${STATE_TEXT[st]}`}
                          onClick={() => {
                            setSelected(c.id)
                            void decide([c.id], toggled(c))
                          }}
                        >
                          {t.text}
                        </button>{' '}
                      </span>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="groups">
            {groups.map(([name, list]) => (
              <section key={name} className="card group" aria-label={`${name} cuts`}>
                <h3 style={{ margin: 0, fontSize: 15 }}>
                  {name} <span className="muted">({list.length})</span>
                </h3>
                <ul>
                  {list.map((c) => {
                    const st = cutState(c)
                    const text = words
                      .filter((w) => w.start >= c.start_s - 0.01 && w.end <= c.end_s + 0.01)
                      .map((w) => w.text)
                      .join(' ')
                    return (
                      <li key={c.id} className={selected === c.id ? 'selected' : undefined}>
                        <button
                          className="btn small"
                          style={{ border: 'none', padding: '0 4px' }}
                          onClick={() => select(c)}
                        >
                          <span className="mono muted">{fmtStamp(c.start_s)}</span>
                        </button>
                        <span
                          className="swatch"
                          style={{ background: REASON_META[c.reason].color }}
                          aria-hidden="true"
                        />
                        <span className="what" lang="vi">
                          {text ||
                            `${REASON_META[c.reason].label} ${(c.end_s - c.start_s).toFixed(1)}s`}
                          {c.source === 'user' && <span className="muted"> · marked by you</span>}
                        </span>
                        <button
                          className="chip"
                          aria-pressed={st === 'kept'}
                          onClick={() => void decide([c.id], true)}
                          aria-label={`Keep ${REASON_META[c.reason].label} at ${fmtStamp(c.start_s)}`}
                        >
                          Keep
                        </button>
                        <button
                          className="chip"
                          aria-pressed={st === 'cut'}
                          onClick={() => void decide([c.id], false)}
                          aria-label={`Cut ${REASON_META[c.reason].label} at ${fmtStamp(c.start_s)}`}
                        >
                          Cut
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            ))}
          </div>
        </section>
      </main>
    </>
  )
}
