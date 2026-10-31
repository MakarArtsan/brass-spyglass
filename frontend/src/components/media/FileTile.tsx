import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { AudioLines, FileText, Film, Image as ImageIcon, Loader2, MoreVertical, TriangleAlert } from 'lucide-react'
import { Lens } from '@/components/Lens'
import { clock, formatDateTime } from '@/lib/format'
import type { Attached } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const icons = { video: Film, image: ImageIcon, audio: AudioLines, document: FileText, link: FileText } as const

interface Props {
  item: Attached
  onOpen: () => void
  onDetach?: () => void
  onDelete?: () => void
}

/** Превью файла в круглой рамке-окуляре: клик открывает просмотр, меню — действия. */
export function FileTile({ item, onOpen, onDetach, onDelete }: Props) {
  const { file } = item
  const Icon = icons[file.kind]
  const name = file.original_name ?? `#${file.id}`
  return (
    <div className="group relative flex w-[104px] flex-col items-center gap-1.5">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`${ru.files.open}: ${name}`}
        className="relative rounded-full p-1.5 outline-none focus-visible:ring-2 focus-visible:ring-brass"
      >
        <Lens decorative size={84} src={file.urls.thumb} alt={name}>
          <span className="flex h-full w-full items-center justify-center bg-ink text-brass">
            {file.processing ? <Loader2 size={26} className="animate-spin" /> : <Icon size={28} />}
          </span>
        </Lens>
        {file.processing && file.urls.thumb && (
          <Loader2 size={16} className="absolute right-1 top-1 animate-spin rounded-full bg-ink p-0.5 text-brass" aria-label={ru.files.processing} />
        )}
        {file.error && (
          <TriangleAlert size={16} className="absolute right-1 top-1 rounded-full bg-ink p-0.5 text-alert" aria-label={ru.files.processingFailed} />
        )}
        {file.kind === 'video' && file.duration_sec != null && (
          <span className="mono absolute bottom-1.5 left-1/2 -translate-x-1/2 rounded bg-black/70 px-1 text-[10px]">{clock(file.duration_sec)}</span>
        )}
      </button>
      <div className="w-full text-center">
        <div className="truncate text-xs" title={name}>
          {name}
        </div>
        <div className={cn('truncate text-[10px] text-fog')} title={formatDateTime(file.uploaded_at)}>
          {file.uploaded_by?.name ?? ru.journal.system}
        </div>
      </div>
      {(onDetach || onDelete) && (
        <Dropdown.Root>
          <Dropdown.Trigger
            aria-label={`${ru.common.more}: ${name}`}
            className="absolute -right-1 top-0 flex min-h-touch min-w-touch items-center justify-center rounded-full text-fog opacity-70 transition-opacity duration-fast hover:text-paper hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100"
          >
            <MoreVertical size={16} />
          </Dropdown.Trigger>
          <Dropdown.Portal>
            <Dropdown.Content align="end" sideOffset={4} className="z-[110] min-w-[200px] rounded-xl border border-line bg-chart p-1 shadow-xl shadow-black/50">
              <Dropdown.Item asChild>
                <a
                  href={`${file.urls.original}&download=true`}
                  className="flex min-h-touch cursor-pointer items-center rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-ink"
                >
                  {ru.files.download}
                </a>
              </Dropdown.Item>
              {onDetach && (
                <Dropdown.Item onSelect={onDetach} className="flex min-h-touch cursor-pointer items-center rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-ink">
                  {ru.files.detach}
                </Dropdown.Item>
              )}
              {onDelete && (
                <Dropdown.Item onSelect={onDelete} className="flex min-h-touch cursor-pointer items-center rounded-lg px-3 text-sm text-alert outline-none data-[highlighted]:bg-ink">
                  {ru.common.delete}
                </Dropdown.Item>
              )}
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      )}
    </div>
  )
}
