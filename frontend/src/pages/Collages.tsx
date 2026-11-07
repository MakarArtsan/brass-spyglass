import { Download, FileArchive, Trash2 } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { Avatar } from '@/components/Avatar'
import { CollageForm } from '@/components/collages/CollageForm'
import { PageHeader } from '@/components/PageHeader'
import { Button, buttonVariants } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { ApiError } from '@/lib/api'
import { useCollages, useDeleteCollage, type Collage } from '@/lib/collages'
import { formatDateTime, formatSize } from '@/lib/format'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

const CollageDialog = lazy(() => import('@/components/collages/CollageDialog'))

function Card({ collage, canDelete, onOpen }: { collage: Collage; canDelete: boolean; onOpen: () => void }) {
  const remove = useDeleteCollage()
  const [asking, setAsking] = useState(false)
  return (
    <li className="flex flex-col overflow-hidden rounded-xl border border-line bg-chart">
      <button type="button" onClick={onOpen} aria-label={ru.collages.open(collage.title)} className="block bg-ink">
        <img
          src={collage.urls.thumb ?? collage.urls.original}
          alt=""
          loading="lazy"
          style={{ aspectRatio: `${collage.width} / ${collage.height}` }}
          className="max-h-[320px] w-full object-contain"
        />
      </button>
      <div className="flex flex-1 flex-col gap-3 p-3">
        <div>
          <h3 className="text-lg leading-tight">{collage.title}</h3>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-fog">
            {collage.created_by && <Avatar user={collage.created_by} className="h-5 w-5" />}
            <span>{collage.created_by?.name ?? ru.journal.system}</span>
            <span>· {formatDateTime(collage.created_at)}</span>
          </p>
          <p className="mono mt-0.5 text-xs text-fog">
            {ru.collages.meta(collage.photos, collage.width, collage.height, formatSize(collage.size_bytes))}
          </p>
        </div>
        <div className="mt-auto flex flex-wrap gap-2">
          <a href={collage.download_url} download className={cn(buttonVariants({ size: 'default' }), 'flex-1')}>
            <Download size={16} aria-hidden />
            {ru.collages.downloadCollage}
          </a>
          <a href={collage.zip_url} download className={cn(buttonVariants({ variant: 'outline' }), 'flex-1')}>
            <FileArchive size={16} aria-hidden />
            {ru.collages.downloadPhotos}
          </a>
        </div>
        {canDelete &&
          (asking ? (
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={ru.collages.deleteAsk(collage.title)}>
              <span className="text-sm">{ru.collages.deleteQuestion}</span>
              <Button
                type="button"
                variant="outline"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(collage.id, {
                    onError: (e) => toast(e instanceof ApiError ? e.message : ru.common.saveFailed),
                    onSettled: () => setAsking(false),
                  })
                }
              >
                {ru.collages.deleteYes}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setAsking(false)}>
                {ru.collages.deleteNo}
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" onClick={() => setAsking(true)} aria-label={ru.collages.delete(collage.title)} className="self-start">
              <Trash2 size={16} aria-hidden />
              {ru.collages.deleteLabel}
            </Button>
          ))}
      </div>
    </li>
  )
}

/** Коллажи: из нескольких фото собирается одна картинка, коллаж получает название; из списка скачивается
 * картинка или исходные фото. */
export default function Collages() {
  const perms = usePerms()
  const { data, isPending, isError, refetch } = useCollages()
  const [open, setOpen] = useState<Collage | null>(null)

  return (
    <section className="space-y-6">
      <PageHeader title={ru.collages.title} lead={ru.collages.lead} />
      {perms.canUpload ? <CollageForm /> : <p className="rounded-xl border border-dashed border-line p-4 text-sm text-fog">{ru.collages.noUpload}</p>}

      <section aria-labelledby="collage-list">
        <h2 id="collage-list" className="mb-3 text-2xl">
          {ru.collages.listTitle}
        </h2>
        {isPending && <p className="text-sm text-fog">{ru.common.loading}</p>}
        {isError && (
          <p role="alert" className="text-sm text-alert">
            {ru.collages.loadFailed}{' '}
            <button type="button" onClick={() => void refetch()} className="min-h-touch underline">
              {ru.app.retry}
            </button>
          </p>
        )}
        {data && data.length === 0 && <p className="text-sm text-fog">{ru.collages.empty}</p>}
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data?.map((collage) => (
            <Card
              key={collage.id}
              collage={collage}
              canDelete={perms.canDelete({ created_by: collage.created_by?.id ?? null })}
              onOpen={() => setOpen(collage)}
            />
          ))}
        </ul>
      </section>

      {open && (
        <Suspense fallback={null}>
          <CollageDialog collage={open} onClose={() => setOpen(null)} />
        </Suspense>
      )}
    </section>
  )
}
