import * as Dialog from '@radix-ui/react-dialog'
import { Maximize, Pause, Play, RotateCcw, SkipBack, SkipForward, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { Segment } from '@/lib/animatic'
import { clock } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

interface Props {
  playlist: Segment[]
  onClose: () => void
  /** Где сейчас на таймлайне (секунды от начала фильма) — для бегунка. */
  onPlayhead: (sec: number | null) => void
}

const TICK_MS = 100

/**
 * «Смотреть фильм»: готовые файлы идут подряд, где файла нет — карточка с описанием на время шота.
 * Видео играет в нашем плеере (с Range), без сторонних плееров.
 */
export default function FilmPlayer({ playlist, onClose, onPlayhead }: Props) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [elapsed, setElapsed] = useState(0)
  const [ended, setEnded] = useState(false)
  const [broken, setBroken] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const stage = useRef<HTMLDivElement>(null)
  const spent = useRef(0) // сколько секунд карточки уже показано (сохраняется на паузе)
  const segment = playlist[index]
  const isFile = segment?.kind === 'file' && !broken
  const cardLength = broken ? 2 : (segment?.duration_sec ?? 0)

  const go = useCallback(
    (to: number) => {
      if (to >= playlist.length) {
        setEnded(true)
        setPlaying(false)
        return
      }
      setIndex(Math.max(0, to))
      spent.current = 0
      setElapsed(0)
      setBroken(false)
      setEnded(false)
    },
    [playlist.length],
  )

  // Карточка и сломанный файл идут по таймеру; видео ведёт сам файл.
  useEffect(() => {
    if (!segment || isFile || !playing || ended) return undefined
    const id = window.setInterval(() => {
      spent.current += TICK_MS / 1000
      setElapsed(spent.current)
      if (spent.current >= cardLength) go(index + 1)
    }, TICK_MS)
    return () => window.clearInterval(id)
  }, [segment, isFile, playing, ended, cardLength, index, go])

  useEffect(() => {
    const element = video.current
    if (!element || !isFile) return
    if (playing) void element.play().catch(() => undefined)
    else element.pause()
  }, [playing, isFile, index])

  // Бегунок на таймлайне.
  useEffect(() => {
    if (!segment || ended) {
      onPlayhead(null)
      return
    }
    const span = segment.end_sec - segment.start_sec
    const share = Math.min(1, elapsed / Math.max(0.001, segment.duration_sec))
    onPlayhead(segment.start_sec + span * share)
  }, [segment, elapsed, ended, onPlayhead])
  useEffect(() => () => onPlayhead(null), [onPlayhead])

  if (!segment) return null
  const total = playlist.reduce((sum, s) => sum + s.duration_sec, 0)
  const before = playlist.slice(0, index).reduce((sum, s) => sum + s.duration_sec, 0)

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[95] bg-black/80" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed inset-x-0 bottom-0 top-0 z-[96] flex flex-col bg-ink outline-none sm:inset-4 sm:rounded-2xl sm:border sm:border-line"
        >
          <div className="flex items-center gap-3 border-b border-line px-4 py-2">
            <Dialog.Title className="min-w-0 flex-1 truncate font-display text-xl">{ru.animatic.watch}</Dialog.Title>
            <span className="mono text-xs text-fog" aria-live="off">
              {clock(before + elapsed)} / {clock(total)}
            </span>
            <button
              type="button"
              onClick={() => void stage.current?.requestFullscreen?.()}
              aria-label={ru.animatic.fullscreen}
              title={ru.animatic.fullscreen}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper"
            >
              <Maximize size={18} />
            </button>
            <Dialog.Close className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.animatic.close}>
              <X size={20} />
            </Dialog.Close>
          </div>

          <div ref={stage} className="relative flex min-h-0 flex-1 items-center justify-center bg-black">
            {ended ? (
              <div className="text-center">
                <p className="font-display text-4xl">{ru.animatic.theEnd}</p>
                <button
                  type="button"
                  onClick={() => {
                    go(0)
                    setPlaying(true)
                  }}
                  className="mt-4 inline-flex min-h-touch items-center gap-2 rounded-lg border border-brass px-4 text-brass hover:bg-chart"
                >
                  <RotateCcw size={16} aria-hidden />
                  {ru.animatic.replay}
                </button>
              </div>
            ) : isFile && segment.file ? (
              <video
                key={`${index}-${segment.file.id}`}
                ref={video}
                src={segment.file.urls.play ?? segment.file.urls.original}
                poster={segment.file.urls.poster}
                autoPlay
                playsInline
                className="h-full w-full object-contain"
                onTimeUpdate={(e) => setElapsed(e.currentTarget.currentTime)}
                onEnded={() => go(index + 1)}
                onError={() => setBroken(true)}
                aria-label={segment.title}
              />
            ) : (
              <div className="mx-auto max-w-2xl p-8 text-center" role="status">
                <p className="mono text-xs uppercase tracking-[0.2em] text-brass">{broken ? ru.animatic.broken : ru.animatic.cardNote}</p>
                <h2 className="mt-3 font-display text-4xl">{segment.title}</h2>
                {segment.description && <p className="mt-4 text-lg text-fog">{segment.description}</p>}
              </div>
            )}
          </div>

          <div className="space-y-2 border-t border-line px-4 py-3">
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => go(index - 1)} disabled={index === 0} aria-label={ru.animatic.prev} className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-paper disabled:opacity-40">
                <SkipBack size={20} />
              </button>
              <button
                type="button"
                onClick={() => {
                  if (ended) {
                    go(0)
                    setPlaying(true)
                  } else setPlaying((value) => !value)
                }}
                aria-label={playing && !ended ? ru.animatic.pause : ru.animatic.play}
                className="flex min-h-touch min-w-touch items-center justify-center rounded-full bg-brass text-on-brass"
              >
                {playing && !ended ? <Pause size={20} /> : <Play size={20} />}
              </button>
              <button type="button" onClick={() => go(index + 1)} aria-label={ru.animatic.next} className="flex min-h-touch min-w-touch items-center justify-center rounded-full text-paper">
                <SkipForward size={20} />
              </button>
              <div className="min-w-0 flex-1 truncate text-sm">
                <span className="text-fog">{ru.animatic.nowPlaying(index + 1, playlist.length)} · </span>
                {segment.title}
              </div>
            </div>
            <div role="group" aria-label={ru.animatic.segments} className="flex h-6 items-stretch gap-px overflow-hidden rounded">
              {playlist.map((s, i) => (
                <button
                  key={`${s.scene_id}-${s.shot_id ?? 's'}-${i}`}
                  type="button"
                  onClick={() => go(i)}
                  aria-label={ru.animatic.segment(i + 1, s.title)}
                  aria-current={i === index ? 'true' : undefined}
                  style={{ flexGrow: s.duration_sec, flexBasis: 0 }}
                  className={cn('min-w-[3px] transition-colors duration-fast', i === index ? 'bg-brass' : i < index ? 'bg-brass/40' : s.kind === 'file' ? 'bg-status-done/60' : 'bg-line')}
                />
              ))}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
