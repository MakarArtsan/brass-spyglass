import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { AudioLines, FileText, Film, Flag, Image as ImageIcon, Link2, Loader2, MoreVertical, TriangleAlert } from 'lucide-react'
import { Lens } from '@/components/Lens'
import { displayName } from '@/lib/files'
import { clock, formatDateTime } from '@/lib/format'
import type { Attached } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const icons = { video: Film, image: ImageIcon, audio: AudioLines, document: FileText, link: Link2 } as const

interface Props {
  item: Attached
  onOpen: () => void
  onDetach?: () => void
  onDelete?: () => void
  /** Открыть историю версий (для ссылок её нет). */
  onVersions?: () => void
  /** Это финальный файл карточки; onFinal переключает отметку. */
  isFinal?: boolean
  onFinal?: () => void
}

/** Превью файла в круглой рамке-окуляре: клик открывает просмотр, меню — действия. */
export function FileTile({ item, onOpen, onDetach, onDelete, onVersions, isFinal, onFinal }: Props) {
  const { file } = item
  const Icon = icons[file.kind]
  const name = displayName(file)
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
        {isFinal && (
          <span className="absolute left-0 top-0 inline-flex items-center gap-0.5 rounded-full bg-brass px-1.5 py-0.5 text-[10px] font-bold text-on-brass">
            <Flag size={10} aria-hidden />
            {ru.files.final}
          </span>
        )}
      </button>
      <div className="w-full text-center">
        <div className="truncate text-xs" title={name}>
          {file.versions_count > 1 && <span className="mono mr-1 text-brass">{ru.files.versionBadge(file.version_no)}</span>}
          {name}
        </div>
        <div className={cn('truncate text-[10px] text-fog')} title={formatDateTime(file.uploaded_at)}>
          {file.uploaded_by?.name ?? ru.journal.system}
        </div>
      </div>
      {(onDetach || onDelete || onVersions || onFinal) && (
        <Dropdown.Root>
          <Dropdown.Trigger
            aria-label={`${ru.common.more}: ${name}`}
            className="group/menu absolute -right-1.5 -top-1.5 flex min-h-touch min-w-touch items-center justify-center rounded-full outline-none"
          >
            {/* Область касания 44 px, а видимая кнопка — кружок на тёмной подложке: на фото значок без фона не виден */}
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-line bg-ink/90 text-paper shadow-md shadow-black/40 transition-colors duration-fast group-hover/menu:border-brass group-focus-visible/menu:ring-2 group-focus-visible/menu:ring-brass">
              <MoreVertical size={18} aria-hidden />
            </span>
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
              {onVersions && file.kind !== 'link' && (
                <Dropdown.Item onSelect={onVersions} className="flex min-h-touch cursor-pointer items-center rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-ink">
                  {ru.files.versions}
                  {file.versions_count > 1 ? ` (${file.versions_count})` : ''}
                </Dropdown.Item>
              )}
              {onFinal && file.kind === 'video' && (
                <Dropdown.Item onSelect={onFinal} className="flex min-h-touch cursor-pointer items-center rounded-lg px-3 text-sm outline-none data-[highlighted]:bg-ink">
                  {isFinal ? ru.files.unsetFinal : ru.files.makeFinal}
                </Dropdown.Item>
              )}
              {onDetach && (
                <Dropdown.Item onSelect={onDetach} className="flex min-h-touch cursor-pointer flex-col justify-center rounded-lg px-3 py-1.5 text-sm outline-none data-[highlighted]:bg-ink">
                  {ru.files.detach}
                  <span className="text-[11px] text-fog">{ru.files.detachHint}</span>
                </Dropdown.Item>
              )}
              {onDelete && (
                <Dropdown.Item onSelect={onDelete} className="flex min-h-touch cursor-pointer flex-col justify-center rounded-lg px-3 py-1.5 text-sm text-alert outline-none data-[highlighted]:bg-ink">
                  {ru.files.deleteFile}
                  <span className="text-[11px] text-fog">{ru.files.deleteHint}</span>
                </Dropdown.Item>
              )}
            </Dropdown.Content>
          </Dropdown.Portal>
        </Dropdown.Root>
      )}
    </div>
  )
}
