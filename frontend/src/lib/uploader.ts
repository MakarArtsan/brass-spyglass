import type { Attached, DuplicateInfo, FileItem } from '@/lib/types'

export interface UploadTarget {
  entityType?: string
  entityId?: number
  purpose?: string
}

export interface UploadHooks {
  onProgress: (loaded: number, total: number) => void
  onState: (state: 'uploading' | 'retrying') => void
  signal: AbortSignal
}

export interface UploadResult {
  file: FileItem
  attachment_id: number | null
}

export class DuplicateError extends Error {
  constructor(
    public info: DuplicateInfo,
    public uploadId: string,
  ) {
    super('duplicate')
  }
}

export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
    public offset?: number,
    public body?: { duplicate?: DuplicateInfo; detail?: unknown },
  ) {
    super(message)
  }
}

class NetworkError extends Error {}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const id = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => {
      clearTimeout(id)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })

function whenOnline(signal: AbortSignal): Promise<void> {
  if (navigator.onLine) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const done = () => {
      window.removeEventListener('online', done)
      resolve()
    }
    window.addEventListener('online', done)
    signal.addEventListener('abort', () => {
      window.removeEventListener('online', done)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

async function json<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, { credentials: 'same-origin', ...init })
  } catch {
    throw new NetworkError('offline')
  }
  if (!res.ok) {
    let body: HttpError['body']
    try {
      body = await res.json()
    } catch {
      /* не JSON */
    }
    const detail = typeof body?.detail === 'string' ? body.detail : res.statusText
    const offset = res.headers.get('Upload-Offset')
    throw new HttpError(res.status, detail, offset ? Number(offset) : undefined, body)
  }
  return (await res.json()) as T
}

/** Один кусок через XHR: только он даёт честный прогресс внутри куска. */
function putChunk(
  uploadId: string,
  offset: number,
  chunk: Blob,
  total: number,
  hooks: UploadHooks,
): Promise<number> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PATCH', `/api/uploads/${uploadId}`)
    xhr.setRequestHeader('Upload-Offset', String(offset))
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (e) => hooks.onProgress(offset + e.loaded, total)
    xhr.onload = () => {
      let body: { offset?: number; detail?: string } = {}
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* пусто */
      }
      if (xhr.status === 200 && typeof body.offset === 'number') resolve(body.offset)
      else {
        const header = xhr.getResponseHeader('Upload-Offset')
        reject(new HttpError(xhr.status, body.detail ?? xhr.statusText, header ? Number(header) : undefined))
      }
    }
    xhr.onerror = () => reject(new NetworkError('network'))
    xhr.ontimeout = () => reject(new NetworkError('timeout'))
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'))
    hooks.signal.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(chunk)
  })
}

/**
 * Загрузка файла кусками с докачкой. При обрыве связи ждёт сеть, спрашивает у сервера,
 * сколько он принял, и продолжает с этого места. Дубль по sha256 сообщается ошибкой
 * DuplicateError — сессия остаётся, и «всё равно добавить» не требует повторной отправки.
 */
export async function uploadFile(
  file: File,
  target: UploadTarget,
  hooks: UploadHooks,
  resume?: { uploadId: string; force: boolean },
): Promise<UploadResult> {
  let uploadId = resume?.uploadId
  let chunkSize = 8 * 1024 * 1024
  if (!uploadId) {
    const init = await json<{ id: string; chunk_size: number }>('/uploads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: file.name, size: file.size, mime: file.type || null }),
      signal: hooks.signal,
    })
    uploadId = init.id
    chunkSize = init.chunk_size
  }

  let offset = resume ? file.size : 0
  let failures = 0
  while (offset < file.size) {
    hooks.signal.throwIfAborted()
    try {
      offset = await putChunk(uploadId, offset, file.slice(offset, offset + chunkSize), file.size, hooks)
      failures = 0
    } catch (err) {
      if (err instanceof DOMException) throw err
      if (err instanceof HttpError) {
        if (err.status === 409 && err.offset !== undefined) {
          offset = err.offset // сервер ушёл вперёд или отстал — продолжаем оттуда
          continue
        }
        throw err
      }
      // обрыв сети: ждём, узнаём у сервера смещение, продолжаем
      hooks.onState('retrying')
      await whenOnline(hooks.signal)
      await sleep(Math.min(30_000, 1000 * 2 ** failures++), hooks.signal)
      try {
        const state = await json<{ offset: number }>(`/uploads/${uploadId}`, { signal: hooks.signal })
        offset = state.offset
        hooks.onState('uploading')
      } catch (inner) {
        if (inner instanceof HttpError) throw inner
      }
    }
  }
  hooks.onProgress(file.size, file.size)

  for (;;) {
    try {
      return await json<UploadResult>(`/uploads/${uploadId}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_type: target.entityType ?? null,
          entity_id: target.entityId ?? null,
          purpose: target.purpose ?? 'reference',
          force: resume?.force ?? false,
        }),
        signal: hooks.signal,
      })
    } catch (err) {
      if (err instanceof NetworkError) {
        await whenOnline(hooks.signal)
        await sleep(1000, hooks.signal)
        continue
      }
      if (err instanceof HttpError && err.status === 409 && err.body?.duplicate) {
        throw new DuplicateError(err.body.duplicate, uploadId)
      }
      throw err
    }
  }
}

export async function cancelUpload(uploadId: string): Promise<void> {
  await fetch(`/api/uploads/${uploadId}`, { method: 'DELETE', credentials: 'same-origin' }).catch(() => undefined)
}

export type { Attached }
