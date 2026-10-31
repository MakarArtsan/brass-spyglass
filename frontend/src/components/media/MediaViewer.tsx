import * as Dialog from '@radix-ui/react-dialog'
import { ChevronLeft, ChevronRight, Download, ExternalLink, FileText, X } from 'lucide-react'
import { useCallback, useEffect, useRef } from 'react'
import { AudioPlayer } from '@/components/media/AudioPlayer'
import { ImageZoom } from '@/components/media/ImageZoom'
import { VideoPlayer } from '@/components/media/VideoPlayer'
import { Avatar } from '@/components/Avatar'
import { formatDateTime, formatSize } from '@/lib/format'
import type { FileItem } from '@/lib/types'
import { ru } from '@/ru'

const sourceLabel = { upload: ru.files.fromUpload, telegram: ru.files.fromTelegram, link: ru.files.fromLink }

function Meta({ file }: { file: FileItem }) {
  const who = file.uploaded_by
  return (
    <div className="flex min-w-0 items-center gap-2 text-xs text-fog">
      {who && <Avatar user={who} className="h-6 w-6 text-[10px]" />}
      <span className="truncate">
        {who ? ru.files.addedBy(who.name, formatDateTime(file.uploaded_at)) : formatDateTime(file.uploaded_at)}
        {' · '}
        {sourceLabel[file.source]}
        {file.size_bytes != null && ` · ${formatSize(file.size_bytes)}`}
        {file.width && file.height && ` · ${file.width}×${file.height}`}
      </span>
    </div>
  )
}

function Body({ file, onSwipe }: { file: FileItem; onSwipe: (d: 1 | -1) => void }) {
  const swipe = useRef<number | null>(null)
  const swipeProps = {
    onPointerDown: (e: React.PointerEvent) => {
      swipe.current = e.clientX
    },
    onPointerUp: (e: React.PointerEvent) => {
      if (swipe.current != null && Math.abs(e.clientX - swipe.current) > 90) onSwipe(e.clientX < swipe.current ? 1 : -1)
      swipe.current = null
    },
  }
  if (file.kind === 'video') return <VideoPlayer key={file.id} file={file} />
  if (file.kind === 'image')
    return <ImageZoom key={file.id} src={file.urls.preview ?? file.urls.original ?? ''} alt={file.original_name ?? ''} onSwipe={onSwipe} />
  if (file.kind === 'audio')
    return (
      <div className="flex h-full w-full items-center justify-center" {...swipeProps}>
        <AudioPlayer key={file.id} file={file} />
      </div>
    )
  if (file.kind === 'document' && file.original_name?.toLowerCase().endsWith('.pdf'))
    return (
      <div className="flex h-full w-full flex-col">
        <iframe key={file.id} src={file.urls.original} title={file.original_name ?? 'PDF'} className="min-h-0 flex-1 bg-white" />
        <a className="p-2 text-center text-xs text-fog underline" href={file.urls.original} target="_blank" rel="noreferrer">
          {ru.viewer.pdfFallback} {ru.files.open}
        </a>
      </div>
    )
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center" {...swipeProps}>
      <FileText size={48} className="text-brass" />
      <p className="text-sm text-fog">{ru.viewer.noPreview}</p>
      <a
        href={`${file.urls.original}&download=true`}
        className="inline-flex min-h-touch items-center gap-2 rounded-lg bg-brass px-4 text-sm font-semibold text-on-brass hover:bg-brass-light"
      >
        <Download size={18} />
        {ru.files.download}
      </a>
    </div>
  )
}

interface Props {
  files: FileItem[]
  index: number
  onIndex: (i: number) => void
  onClose: () => void
}

/**
 * Просмотр поверх страницы (ТЗ): на ПК — лайтбокс со стрелками ← →, на телефоне — на весь
 * экран со свайпом между файлами. Видео, фото, аудио и PDF проигрываются прямо на сайте.
 */
export function MediaViewer({ files, index, onIndex, onClose }: Props) {
  const file = files[index]
  const go = useCallback(
    (direction: 1 | -1) => onIndex((index + direction + files.length) % files.length),
    [index, files.length, onIndex],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowLeft') go(-1)
      else if (e.key === 'ArrowRight') go(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go])

  if (!file) return null
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[100] bg-black/90" />
        <Dialog.Content
          aria-describedby={undefined}
          className="pt-safe pb-safe fixed inset-0 z-[101] flex flex-col outline-none lg:inset-6 lg:overflow-hidden lg:rounded-2xl lg:border lg:border-line lg:bg-black"
        >
          <header className="flex items-center gap-3 px-4 py-2">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="truncate font-sans text-sm font-semibold">{file.original_name ?? ru.viewer.title}</Dialog.Title>
              <Meta file={file} />
            </div>
            {files.length > 1 && (
              <span className="mono text-xs text-fog" aria-label={`${index + 1} / ${files.length}`}>
                {index + 1} / {files.length}
              </span>
            )}
            <a
              href={`${file.urls.original}&download=true`}
              aria-label={ru.files.download}
              title={ru.files.download}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:bg-white/10 hover:text-paper"
            >
              <Download size={20} />
            </a>
            <a
              href={file.urls.original}
              target="_blank"
              rel="noreferrer"
              aria-label={ru.files.open}
              title={ru.files.open}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:bg-white/10 hover:text-paper max-lg:hidden"
            >
              <ExternalLink size={20} />
            </a>
            <Dialog.Close
              aria-label={ru.common.close}
              className="flex min-h-touch min-w-touch items-center justify-center rounded-lg text-fog hover:bg-white/10 hover:text-paper"
            >
              <X size={22} />
            </Dialog.Close>
          </header>
          <div className="relative min-h-0 flex-1">
            <Body file={file} onSwipe={go} />
            {files.length > 1 && (
              <>
                <button
                  type="button"
                  aria-label={ru.viewer.prev}
                  onClick={() => go(-1)}
                  className="absolute left-2 top-1/2 flex min-h-touch min-w-touch -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-paper hover:bg-black/80 max-lg:hidden"
                >
                  <ChevronLeft size={26} />
                </button>
                <button
                  type="button"
                  aria-label={ru.viewer.next}
                  onClick={() => go(1)}
                  className="absolute right-2 top-1/2 flex min-h-touch min-w-touch -translate-y-1/2 items-center justify-center rounded-full bg-black/60 text-paper hover:bg-black/80 max-lg:hidden"
                >
                  <ChevronRight size={26} />
                </button>
              </>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
