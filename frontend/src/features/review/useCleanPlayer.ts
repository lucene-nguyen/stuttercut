// Web Audio clean preview (ADR 0005): the preview WAV plays the plan's keep-segments back to back
// on the AudioContext clock with the render's fades; the muted video follows the audio.
import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

import { api } from '../../api/client'
import { gainRamp, schedule, snapToKeep, sourceAt, type Plan, type Scheduled } from './cleanAudio'

const DRIFT_S = 0.08 // the video is re-seeked when it is further than this from the audio
const LEAD_S = 0.05 // schedule slightly ahead so the first part never starts in the past

function createContext(): AudioContext {
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  return new Ctor()
}

export interface CleanPlayer {
  audio: AudioBuffer | null
  loading: boolean
  error: string
  playing: boolean
  position: number // source seconds
  plan: Plan | null
  play: () => Promise<void>
  pause: () => void
  seek: (t: number) => void
  playAround: (t: number) => Promise<void>
  reloadPlan: () => Promise<void>
  loadAudio: () => Promise<AudioBuffer | null>
}

export function useCleanPlayer(
  jobId: string,
  video: RefObject<HTMLVideoElement | null>,
): CleanPlayer {
  const ctx = useRef<AudioContext | null>(null)
  const buffer = useRef<AudioBuffer | null>(null)
  const decoding = useRef<Promise<AudioBuffer> | null>(null)
  const plan = useRef<Plan | null>(null)
  const parts = useRef<Scheduled[]>([])
  const nodes = useRef<AudioBufferSourceNode[]>([])
  const raf = useRef(0)
  const pos = useRef(0)
  const isPlaying = useRef(false)
  const [audio, setAudio] = useState<AudioBuffer | null>(null)
  const [planState, setPlan] = useState<Plan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)

  const getContext = () => (ctx.current ??= createContext())

  /** Safari keeps a new AudioContext suspended until a user gesture resumes it. */
  const running = useCallback(async () => {
    const c = getContext()
    if (c.state === 'suspended') await c.resume()
    return c
  }, [])

  const loadAudio = useCallback(async () => {
    if (buffer.current) return buffer.current
    if (!decoding.current) {
      setLoading(true)
      decoding.current = (async () => {
        const res = await fetch(api.previewAudioUrl(jobId))
        if (!res.ok) throw new Error(`preview audio: ${res.status} ${res.statusText}`)
        const data = await res.arrayBuffer()
        // callback form: older Safari has no promise-returning decodeAudioData
        return new Promise<AudioBuffer>((ok, bad) => getContext().decodeAudioData(data, ok, bad))
      })()
    }
    try {
      buffer.current = await decoding.current
      setAudio(buffer.current)
      setError('')
      return buffer.current
    } catch (e) {
      decoding.current = null
      setError(`Could not load the preview audio (${(e as Error).message}).`)
      return null
    } finally {
      setLoading(false)
    }
  }, [jobId])

  const stopNodes = () => {
    cancelAnimationFrame(raf.current)
    for (const n of nodes.current) {
      n.onended = null
      try {
        n.stop()
      } catch {
        // already stopped
      }
    }
    nodes.current = []
  }

  const finish = useCallback(() => {
    stopNodes()
    isPlaying.current = false
    setPlaying(false)
    video.current?.pause()
  }, [video])

  /** Schedule every keep-segment from source position ``from`` and let the video follow. */
  const start = useCallback(
    (from: number) => {
      const c = ctx.current
      const buf = buffer.current
      const p = plan.current
      if (!c || !buf || !p) return
      stopNodes()
      const sched = schedule(p.keep_segments, from, c.currentTime + LEAD_S)
      if (sched.length === 0) return finish()
      for (const part of sched) {
        const src = c.createBufferSource()
        src.buffer = buf
        const gain = c.createGain()
        gainRamp(part, p.fade_ms / 1000).forEach(([t, g], i) =>
          i === 0 ? gain.gain.setValueAtTime(g, t) : gain.gain.linearRampToValueAtTime(g, t),
        )
        src.connect(gain).connect(c.destination)
        src.start(part.when, part.offset, part.duration)
        nodes.current.push(src)
      }
      parts.current = sched
      const v = video.current
      if (v) {
        v.muted = true
        v.currentTime = sched[0].offset
        void v.play().catch(() => undefined)
      }
      let segment = sched[0].segment
      let shown = -1
      const tick = () => {
        const now = c.currentTime
        const t = sourceAt(parts.current, now)
        if (t === null) return finish()
        pos.current = t
        if (Math.abs(t - shown) >= 0.1) {
          shown = t
          setPosition(t) // ~10 Hz is enough for the playhead and the clock
        }
        const cur = parts.current.find((x) => now < x.when + x.duration)?.segment ?? segment
        if (v) {
          if (cur !== segment || Math.abs(v.currentTime - t) > DRIFT_S) v.currentTime = t
          if (v.paused) void v.play().catch(() => undefined)
        }
        segment = cur
        raf.current = requestAnimationFrame(tick)
      }
      raf.current = requestAnimationFrame(tick)
    },
    [finish, video],
  )

  const reloadPlan = useCallback(async () => {
    plan.current = await api.plan(jobId)
    setPlan(plan.current)
    if (isPlaying.current) start(pos.current) // reschedule from where the listener is
  }, [jobId, start])

  const play = useCallback(async () => {
    await running() // inside the click / key press: required by Safari
    const buf = await loadAudio()
    if (!buf) return
    if (!plan.current) await reloadPlan()
    const keeps = plan.current?.keep_segments ?? []
    const from = snapToKeep(pos.current, keeps) ?? keeps[0]?.start_s ?? 0 // at the end: replay
    isPlaying.current = true
    setPlaying(true)
    start(from)
  }, [loadAudio, reloadPlan, running, start])

  const pause = useCallback(() => {
    stopNodes()
    isPlaying.current = false
    setPlaying(false)
    video.current?.pause()
  }, [video])

  const seek = useCallback(
    (t: number) => {
      const keeps = plan.current?.keep_segments ?? []
      const to = keeps.length ? (snapToKeep(t, keeps) ?? keeps[keeps.length - 1].end_s) : t
      pos.current = to
      setPosition(to)
      if (video.current) video.current.currentTime = to
      if (isPlaying.current) start(to)
    },
    [start, video],
  )

  /** 1 s of normal (uncut) audio around ``t``, to check a cut edge by ear. */
  const playAround = useCallback(
    async (t: number) => {
      const c = await running()
      const buf = await loadAudio()
      if (!buf) return
      const src = c.createBufferSource()
      src.buffer = buf
      src.connect(c.destination)
      src.start(c.currentTime, Math.max(0, t - 0.5), 1)
    },
    [loadAudio, running],
  )

  useEffect(
    () => () => {
      stopNodes()
      void ctx.current?.close()
    },
    [],
  )

  return {
    audio,
    loading,
    error,
    playing,
    position,
    plan: planState,
    play,
    pause,
    seek,
    playAround,
    reloadPlan,
    loadAudio,
  }
}
