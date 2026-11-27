import { useEffect, useRef, useState } from 'react'

import type { Cut } from '../../api/client'
import { NUDGE_S, fmtEdge, nudge, peaks } from './cleanAudio'
import { REASON_META } from './logic'

const AROUND_S = 1.5 // the strip shows this much on each side of the cut
const WIDTH = 1000 // canvas pixels; CSS scales it to the panel

interface Props {
  cut: Cut
  duration: number
  audio: AudioBuffer | null
  loading: boolean
  effective: { start: number; end: number } | null // where the plan really cuts (frame-snapped)
  onEdges: (start: number, end: number) => void
  onPlayAround: (t: number) => void
}

export default function EdgeEditor({
  cut,
  duration,
  audio,
  loading,
  effective,
  onEdges,
  onPlayAround,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const strip = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ start: number; end: number } | null>(null)
  const from = Math.max(0, Math.min(cut.orig_start_s, cut.start_s) - AROUND_S)
  const to = Math.min(duration, Math.max(cut.orig_end_s, cut.end_s) + AROUND_S)
  const edges = drag ?? { start: cut.start_s, end: cut.end_s }
  const pct = (t: number) => `${((t - from) / (to - from || 1)) * 100}%`
  const color = REASON_META[cut.reason].color
  const edited = Boolean(cut.start_edited || cut.end_edited)

  useEffect(() => {
    const c = canvas.current?.getContext('2d')
    if (!c || !canvas.current) return
    const h = canvas.current.height
    c.clearRect(0, 0, WIDTH, h)
    if (!audio) return
    c.fillStyle = '#7E8696'
    peaks(audio.getChannelData(0), audio.sampleRate, from, to, WIDTH).forEach(([lo, hi], x) => {
      const y1 = ((1 - hi) / 2) * h
      const y2 = ((1 - lo) / 2) * h
      c.fillRect(x, y1, 1, Math.max(1, y2 - y1))
    })
  }, [audio, from, to])

  const timeAt = (clientX: number) => {
    const r = strip.current!.getBoundingClientRect()
    return from + ((clientX - r.left) / r.width) * (to - from)
  }

  const dragHandle = (edge: 'start' | 'end') => ({
    onPointerDown: (e: React.PointerEvent<HTMLButtonElement>) => {
      e.stopPropagation()
      e.currentTarget.setPointerCapture(e.pointerId)
      setDrag({ start: cut.start_s, end: cut.end_s })
    },
    onPointerMove: (e: React.PointerEvent<HTMLButtonElement>) => {
      if (!drag) return
      const t = timeAt(e.clientX)
      setDrag((d) => (d ? nudge(d, edge, t - d[edge], duration) : d))
    },
    onPointerUp: () => {
      if (drag && (drag.start !== cut.start_s || drag.end !== cut.end_s))
        onEdges(drag.start, drag.end)
      setDrag(null)
    },
  })

  const step = (edge: 'start' | 'end', dir: 1 | -1) => {
    const n = nudge({ start: cut.start_s, end: cut.end_s }, edge, dir * NUDGE_S, duration)
    onEdges(n.start, n.end)
  }

  return (
    <section className="card edge-editor" aria-label="Cut edges">
      <div className="row spread">
        <h3 style={{ margin: 0, fontSize: 15 }}>
          Edges of the {REASON_META[cut.reason].label.toLowerCase()} cut
          {edited && <span className="muted"> · edited (no padding on moved edges)</span>}
        </h3>
        <button
          className="btn small"
          disabled={!edited}
          onClick={() => onEdges(cut.orig_start_s, cut.orig_end_s)}
        >
          Reset edges
        </button>
      </div>
      <div
        ref={strip}
        className="edge-strip"
        title="Click to hear 1 s around this point"
        onPointerDown={(e) => onPlayAround(timeAt(e.clientX))}
      >
        <canvas ref={canvas} width={WIDTH} height={80} aria-hidden="true" />
        {!audio && <span className="edge-loading muted">{loading ? 'Loading audio…' : ''}</span>}
        <span
          className="edge-region"
          style={{
            left: pct(edges.start),
            width: `calc(${pct(edges.end)} - ${pct(edges.start)})`,
            background: color,
          }}
        />
        {effective && (
          <span
            className="edge-effective"
            style={{
              left: pct(effective.start),
              width: `calc(${pct(effective.end)} - ${pct(effective.start)})`,
            }}
            title="What the render cuts: segments snap to whole frames"
          />
        )}
        {edited && (
          <>
            <span
              className="edge-orig"
              style={{ left: pct(cut.orig_start_s) }}
              aria-hidden="true"
            />
            <span className="edge-orig" style={{ left: pct(cut.orig_end_s) }} aria-hidden="true" />
          </>
        )}
        {(['start', 'end'] as const).map((edge) => (
          <button
            key={edge}
            className="edge-handle"
            style={{ left: pct(edges[edge]) }}
            aria-label={`${edge === 'start' ? 'Start' : 'End'} edge at ${fmtEdge(edges[edge])}; drag it, or use ${edge === 'start' ? 'Alt' : 'Shift'}+arrow keys`}
            {...dragHandle(edge)}
          />
        ))}
      </div>
      <div className="row spread mono" style={{ fontSize: 14 }}>
        {(['start', 'end'] as const).map((edge) => (
          <div key={edge} className="row" style={{ gap: 6 }}>
            <span>
              {edge === 'start' ? 'Start' : 'End'}{' '}
              <b data-testid={`edge-${edge}`}>{fmtEdge(edges[edge])}</b> set ·{' '}
              <span className="muted" title="The render snaps to whole frames">
                <span data-testid={`edge-${edge}-eff`}>
                  {effective ? fmtEdge(effective[edge]) : '—'}
                </span>{' '}
                effective
              </span>
            </span>
            <button
              className="btn small"
              aria-label={`${edge === 'start' ? 'Start' : 'End'} 10 ms earlier`}
              onClick={() => step(edge, -1)}
            >
              −10 ms
            </button>
            <button
              className="btn small"
              aria-label={`${edge === 'start' ? 'Start' : 'End'} 10 ms later`}
              onClick={() => step(edge, 1)}
            >
              +10 ms
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
