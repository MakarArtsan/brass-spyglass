import * as Dialog from '@radix-ui/react-dialog'
import { Download, FileArchive, X } from 'lucide-react'
import { buttonVariants } from '@/components/ui/button'
import { useCollage, type Collage } from '@/lib/collages'
import { formatSize } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

/** Коллаж крупно и список фото, из которых он собран; отсюда же скачиваются картинка и исходники. */
export default function CollageDialog({ collage, onClose }: { collage: Collage; onClose: () => void }) {
  const detail = useCollage(collage.id)
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-black/70" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-[91] flex max-h-[92dvh] w-[min(96vw,1100px)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-2xl border border-line bg-chart p-4 shadow-2xl outline-none sm:p-6">
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="font-display text-2xl">{collage.title}</Dialog.Title>
            <Dialog.Close className="flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-full text-fog hover:text-paper" aria-label={ru.collages.close}>
              <X size={18} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="text-sm text-fog">{ru.collages.dialogLead(collage.photos, collage.width, collage.height)}</Dialog.Description>
          <img src={collage.urls.preview ?? collage.urls.original} alt={collage.title} className="max-h-[60dvh] w-full rounded-xl bg-ink object-contain" />
          <div className="flex flex-wrap gap-3">
            <a href={collage.download_url} download className={cn(buttonVariants())}>
              <Download size={16} aria-hidden />
              {ru.collages.downloadCollage}
            </a>
            <a href={collage.zip_url} download className={cn(buttonVariants({ variant: 'outline' }))}>
              <FileArchive size={16} aria-hidden />
              {ru.collages.downloadPhotos}
            </a>
          </div>
          <div>
            <h3 className="mb-2 text-lg">{ru.collages.fromPhotos}</h3>
            {detail.isPending && <p className="text-sm text-fog">{ru.common.loading}</p>}
            <ol className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {detail.data?.photo_list.map((photo, index) => (
                <li key={photo.id} className="overflow-hidden rounded-lg border border-line bg-ink">
                  <div className="relative aspect-[4/3]">
                    <img src={photo.urls.thumb ?? photo.urls.original} alt={photo.original_name ?? ''} loading="lazy" className="h-full w-full object-contain" />
                    <span className="mono absolute left-1 top-1 rounded bg-ink/80 px-1 text-[11px] text-brass">{index + 1}</span>
                  </div>
                  <p className="truncate px-1.5 pt-1 text-[11px]" title={photo.original_name ?? ''}>
                    {photo.original_name}
                  </p>
                  <p className="px-1.5 pb-1 text-[10px] text-fog">
                    {photo.width && photo.height ? `${photo.width}×${photo.height} · ` : ''}
                    {formatSize(photo.size_bytes)}
                  </p>
                </li>
              ))}
            </ol>
            {detail.data && detail.data.photo_list.length < collage.photos && <p className="mt-2 text-xs text-fog">{ru.collages.someGone}</p>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
