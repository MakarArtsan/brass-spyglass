import { Link2 } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { LibraryView } from '@/components/media/LibraryView'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import type { FileItem, LibraryItem } from '@/lib/types'
import { ru } from '@/ru'

// Окно просмотра (плееры, wavesurfer) тяжёлое — грузим при первом открытии файла.
const MediaViewer = lazy(() => import('@/components/media/MediaViewer').then((m) => ({ default: m.MediaViewer })))
const LinkDialog = lazy(() => import('@/components/media/LinkDialog'))

const viewable = (file: FileItem): boolean => file.kind !== 'link' && !(file.kind === 'document' && !file.original_name?.toLowerCase().endsWith('.pdf'))

/** Медиатека: все файлы проекта сеткой и списком, фильтры по типу, источнику, автору, дате и «без привязки». */
export default function Media() {
  const perms = usePerms()
  const [viewer, setViewer] = useState<{ files: LibraryItem[]; index: number } | null>(null)
  const [adding, setAdding] = useState(false)

  const open = (item: LibraryItem, all: LibraryItem[]) => {
    if (item.kind === 'link') {
      if (item.url) window.open(item.url, '_blank', 'noopener,noreferrer')
      return
    }
    if (!viewable(item)) {
      window.open(`${item.urls.original}&download=true`, '_self')
      return
    }
    const files = all.filter(viewable)
    setViewer({ files, index: files.findIndex((f) => f.id === item.id) })
  }

  return (
    <div>
      <PageHeader
        title={ru.library.title}
        lead={ru.library.lead}
        actions={
          perms.canUpload && (
            <Button type="button" variant="outline" onClick={() => setAdding(true)}>
              <Link2 size={18} />
              {ru.library.addLink}
            </Button>
          )
        }
      />
      <LibraryView mode="page" onOpen={open} />
      {viewer && (
        <Suspense fallback={null}>
          <MediaViewer files={viewer.files} index={viewer.index} onIndex={(index) => setViewer({ ...viewer, index })} onClose={() => setViewer(null)} />
        </Suspense>
      )}
      {adding && (
        <Suspense fallback={null}>
          <LinkDialog onClose={() => setAdding(false)} />
        </Suspense>
      )}
    </div>
  )
}
