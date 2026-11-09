import { useEffect, useRef, useState } from 'react'
import { ApiError } from '@/lib/api'
import { MAX_PHOTOS } from '@/lib/collages'
import { toast } from '@/lib/toast'
import { cancelUpload, DuplicateError, uploadFile } from '@/lib/uploader'
import { ru } from '@/ru'

const IMAGE_NAME = /\.(jpe?g|jfif|jpe|png|webp|heic|heif|avif|gif|bmp|tiff?)$/i

/** Фото в списке коллажа: либо уже лежит в проекте (`fileId`), либо выбрано на устройстве и ещё не загружено (`file`). */
export interface PhotoItem {
  key: string
  name: string
  /** Адрес картинки для показа: blob: у новых, ссылка сервера у сохранённых. */
  preview: string | null
  size: number | null
  file?: File
  fileId?: number
  broken: boolean
  status: 'idle' | 'uploading' | 'done' | 'error'
  progress: number
}

let counter = 0
const nextKey = () => `p${++counter}`

export const isPhoto = (file: File) => file.type.startsWith('image/') || IMAGE_NAME.test(file.name)

/** Фото, уже лежащее в проекте. */
export const savedPhoto = (id: number, name: string | null, preview: string | null, size: number | null): PhotoItem => ({
  key: `s${id}`,
  name: name ?? ru.collages.photoFallback(id),
  preview,
  size,
  fileId: id,
  broken: false,
  status: 'idle',
  progress: 0,
})

/** Список фото коллажа: добавить (с проверкой «это фото» и потолком в 10), убрать, сдвинуть. Ссылки на
 * выбранные файлы освобождаются сами. */
export function usePhotoItems(initial: PhotoItem[] = []) {
  const [items, setItems] = useState<PhotoItem[]>(initial)
  const blobs = useRef<string[]>([])
  useEffect(
    () => () => {
      blobs.current.forEach((url) => URL.revokeObjectURL(url))
    },
    [],
  )

  const patch = (key: string, change: Partial<PhotoItem>) =>
    setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)))

  const add = (list: FileList | null): boolean => {
    if (!list || list.length === 0) return false
    const photos = Array.from(list).filter((file) => {
      if (isPhoto(file)) return true
      toast(ru.collages.notPhoto(file.name))
      return false
    })
    const room = Math.max(0, MAX_PHOTOS - items.length)
    if (photos.length > room) toast(ru.collages.tooMany(MAX_PHOTOS))
    const taken = photos.slice(0, room).map<PhotoItem>((file) => {
      const preview = URL.createObjectURL(file)
      blobs.current.push(preview)
      return { key: nextKey(), name: file.name, preview, size: file.size, file, broken: false, status: 'idle', progress: 0 }
    })
    setItems((old) => [...old, ...taken])
    return taken.length > 0
  }

  const remove = (key: string) => setItems((list) => list.filter((item) => item.key !== key))
  const move = (index: number, by: -1 | 1) =>
    setItems((list) => {
      const next = [...list]
      ;[next[index], next[index + by]] = [next[index + by], next[index]]
      return next
    })

  return { items, setItems, patch, add, remove, move }
}

/** Загрузка не удалась на конкретном фото: сообщение для человека. */
export class PhotoUploadError extends Error {}

/**
 * Загружает по одному те фото, которых ещё нет в проекте (без сжатия: исходники остаются как есть) и
 * возвращает id всех фото по порядку. Фото, которое в проекте уже есть (дубль по sha256), берётся
 * готовое. Загруженное один раз повторно не отправляется. Отмена — `AbortError`.
 */
export async function uploadMissing(
  items: PhotoItem[],
  patch: (key: string, change: Partial<PhotoItem>) => void,
  signal: AbortSignal,
): Promise<number[]> {
  const ids: number[] = []
  for (const item of items) {
    let id = item.fileId
    if (id === undefined && item.file) {
      patch(item.key, { status: 'uploading', progress: 0 })
      try {
        const done = await uploadFile(
          item.file,
          { noCompress: true, purpose: 'reference' },
          {
            onProgress: (loaded, total) => patch(item.key, { progress: total ? loaded / total : 0 }),
            onState: () => undefined,
            signal,
          },
        )
        id = done.file.id
      } catch (e) {
        if (e instanceof DuplicateError) {
          void cancelUpload(e.uploadId) // такое фото в проекте уже есть: берём его, не загружая заново
          id = e.info.file_id
        } else if (e instanceof DOMException) {
          throw e
        } else {
          patch(item.key, { status: 'error' })
          throw new PhotoUploadError(e instanceof ApiError ? e.message : ru.collages.uploadFailed(item.name))
        }
      }
      patch(item.key, { status: 'done', progress: 1, fileId: id })
    }
    if (id === undefined) throw new PhotoUploadError(ru.collages.uploadFailed(item.name))
    if (ids.includes(id)) {
      patch(item.key, { status: 'error' })
      throw new PhotoUploadError(ru.collages.sameTwice(item.name))
    }
    ids.push(id)
  }
  return ids
}

export const sameIds = (a: number[], b: number[]) => a.length === b.length && a.every((id, i) => id === b[i])
