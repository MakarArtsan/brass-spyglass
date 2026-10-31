import { Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { api } from '@/lib/api'
import { clock } from '@/lib/format'
import { cssColor } from '@/lib/utils'
import type { FileItem } from '@/lib/types'
import { ru } from '@/ru'

/** Аудио с волной (wavesurfer.js): клик по волне — перемотка. Волну считает сервер заранее. */
export function AudioPlayer({ file }: { file: FileItem }) {
  const host = useRef<HTMLDivElement>(null)
  const surfer = useRef<WaveSurfer | null>(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(file.duration_sec ?? 0)

  useEffect(() => {
    let cancelled = false
    const mount = async () => {
      if (!host.current || !file.urls.play) return
      let peaks: number[] | undefined
      if (file.urls.waveform) {
        try {
          peaks = await api<number[]>(file.urls.waveform.replace(/^\/api/, ''))
        } catch {
          /* волну досчитает браузер */
        }
      }
      if (cancelled || !host.current) return
      const ws = WaveSurfer.create({
        container: host.current,
        url: file.urls.play,
        peaks: peaks ? [peaks] : undefined,
        duration: peaks ? (file.duration_sec ?? undefined) : undefined,
        height: 140,
        barWidth: 3,
        barGap: 2,
        barRadius: 2,
        waveColor: cssColor('fog'),
        progressColor: cssColor('brass'),
        cursorColor: cssColor('brass-light'),
      })
      ws.on('play', () => setPlaying(true))
      ws.on('pause', () => setPlaying(false))
      ws.on('timeupdate', (t) => setCurrent(t))
      ws.on('ready', (d) => setDuration(d))
      surfer.current = ws
    }
    void mount()
    return () => {
      cancelled = true
      surfer.current?.destroy()
      surfer.current = null
    }
  }, [file.urls.play, file.urls.waveform, file.duration_sec])

  return (
    <div className="w-full max-w-3xl space-y-4 px-6">
      <div ref={host} aria-label={ru.viewer.waveform} className="rounded-xl border border-line bg-chart p-4" />
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label={playing ? ru.viewer.pause : ru.viewer.play}
          onClick={() => surfer.current?.playPause()}
          className="flex min-h-touch min-w-touch items-center justify-center rounded-full bg-brass text-on-brass transition-colors duration-fast hover:bg-brass-light"
        >
          {playing ? <Pause size={22} /> : <Play size={22} />}
        </button>
        <span className="mono text-sm">
          {clock(current)} / {clock(duration)}
        </span>
      </div>
    </div>
  )
}
