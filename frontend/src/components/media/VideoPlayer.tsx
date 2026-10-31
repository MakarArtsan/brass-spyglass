import {
  ChevronLeft,
  ChevronRight,
  Maximize,
  Minimize,
  Pause,
  Play,
  Repeat,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { clock } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { FileItem } from '@/lib/types'
import { ru } from '@/ru'

const SPEEDS = [0.25, 0.5, 1, 1.5, 2]

function IconButton({ label, onClick, active, children }: { label: string; onClick: () => void; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        'flex min-h-touch min-w-touch items-center justify-center rounded-lg text-paper transition-colors duration-fast hover:bg-white/10',
        active && 'bg-brass/20 text-brass-light',
      )}
    >
      {children}
    </button>
  )
}

/**
 * Свой плеер (ТЗ): перемотка, покадровый шаг «,» и «.», скорость 0.25–2×, повтор фрагмента
 * и полный экран. Играет наш файл с диска, без YouTube и рекламы.
 */
export function VideoPlayer({ file }: { file: FileItem }) {
  const video = useRef<HTMLVideoElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(file.duration_sec ?? 0)
  const [rate, setRate] = useState(1)
  const [loop, setLoop] = useState<{ a: number | null; b: number | null }>({ a: null, b: null })
  const [fullscreen, setFullscreen] = useState(false)
  const [failed, setFailed] = useState(false)
  const fps = file.fps || 24
  const looping = loop.a != null && loop.b != null && loop.b > loop.a

  const toggle = useCallback(() => {
    const v = video.current
    if (!v) return
    if (v.paused) void v.play()
    else v.pause()
  }, [])

  const step = useCallback(
    (direction: 1 | -1) => {
      const v = video.current
      if (!v) return
      v.pause()
      v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + direction / fps))
    },
    [fps],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (e.key === ' ') {
        e.preventDefault()
        toggle()
      } else if (e.key === ',') step(-1)
      else if (e.key === '.') step(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, step])

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === frame.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const onTimeUpdate = () => {
    const v = video.current
    if (!v) return
    setCurrent(v.currentTime)
    if (looping && loop.b != null && loop.a != null && v.currentTime >= loop.b) v.currentTime = loop.a
  }

  const setRateTo = (value: number) => {
    setRate(value)
    if (video.current) video.current.playbackRate = value
  }

  const markLoop = () => {
    const t = video.current?.currentTime ?? 0
    setLoop((l) => (l.a == null || (l.a != null && l.b != null) ? { a: t, b: null } : { a: l.a, b: Math.max(t, l.a + 0.1) }))
  }

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void frame.current?.requestFullscreen()
  }

  if (failed) return <p className="max-w-md p-6 text-center text-sm text-fog">{ru.viewer.cantPlay}</p>

  return (
    <div ref={frame} className="flex h-full w-full flex-col bg-black">
      <div className="relative min-h-0 flex-1">
        <video
          ref={video}
          src={file.urls.play}
          poster={file.urls.poster}
          playsInline
          preload="metadata"
          onClick={toggle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={onTimeUpdate}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-contain"
        />
      </div>
      <div className="space-y-1 px-3 pb-2 pt-1">
        <div className="relative">
          <input
            type="range"
            aria-label={ru.viewer.seek}
            min={0}
            max={duration || 0}
            step={0.01}
            value={current}
            onChange={(e) => {
              if (video.current) video.current.currentTime = Number(e.target.value)
            }}
            className="h-6 w-full cursor-pointer accent-[rgb(var(--brass))]"
          />
          {loop.a != null && duration > 0 && (
            <span
              aria-hidden
              className="pointer-events-none absolute top-1/2 h-2 -translate-y-1/2 rounded bg-brass/40"
              style={{ left: `${(loop.a / duration) * 100}%`, width: `${(((loop.b ?? loop.a) - loop.a) / duration) * 100}%`, minWidth: 3 }}
            />
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <IconButton label={playing ? ru.viewer.pause : ru.viewer.play} onClick={toggle}>
            {playing ? <Pause size={20} /> : <Play size={20} />}
          </IconButton>
          <IconButton label={ru.viewer.frameBack} onClick={() => step(-1)}>
            <ChevronLeft size={20} />
          </IconButton>
          <IconButton label={ru.viewer.frameForward} onClick={() => step(1)}>
            <ChevronRight size={20} />
          </IconButton>
          <span className="mono min-w-[88px] px-2 text-sm text-paper" aria-label={ru.viewer.time}>
            {clock(current)} / {clock(duration)}
          </span>
          <select
            aria-label={ru.viewer.speed}
            value={rate}
            onChange={(e) => setRateTo(Number(e.target.value))}
            className="mono min-h-touch rounded-lg bg-transparent px-2 text-sm text-paper outline-none hover:bg-white/10"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s} className="bg-chart">
                {s}×
              </option>
            ))}
          </select>
          <IconButton label={looping ? ru.viewer.loopOn : ru.viewer.loopSet} onClick={markLoop} active={looping || loop.a != null}>
            <Repeat size={20} />
          </IconButton>
          {loop.a != null && (
            <>
              <span className="mono text-xs text-fog">
                {clock(loop.a)}–{loop.b != null ? clock(loop.b) : '…'}
              </span>
              <IconButton label={ru.viewer.loopClear} onClick={() => setLoop({ a: null, b: null })}>
                <X size={18} />
              </IconButton>
            </>
          )}
          <span className="flex-1" />
          <IconButton label={fullscreen ? ru.viewer.exitFullscreen : ru.viewer.fullscreen} onClick={toggleFullscreen}>
            {fullscreen ? <Minimize size={20} /> : <Maximize size={20} />}
          </IconButton>
        </div>
      </div>
    </div>
  )
}
