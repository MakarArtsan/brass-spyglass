import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { invalidateResource, type Resource } from '@/lib/queries'

/**
 * Живые обновления: один поток SSE на вкладку. В событиях только «что изменилось»; данные клиент
 * перечитывает обычными запросами, поэтому права доступа проверяются как всегда.
 */

const RESOURCE_OF: Record<string, Resource | undefined> = {
  scene: 'scenes',
  shot: 'shots',
  asset: 'assets',
  asset_state: 'assets',
  setup_payoff: 'setups',
  sound_cue: 'sound',
  task: 'tasks',
}

/** События собираются в окно, чтобы пачка из 20 файлов не вызывала 20 перезапросов. */
const FLUSH_MS = 250
const RETRY_MIN_MS = 3_000
const RETRY_MAX_MS = 30_000

export interface JobEvent {
  type: 'job'
  id: number
  job_type: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  file_id: number | null
  created_by: number | null
}

type LiveEvent =
  | { type: 'hello' }
  | { type: 'resync' }
  | { type: 'activity'; action: string; entity_type: string; entity_id: number | null; actor_id: number | null }
  | { type: 'tg'; topic_id: number | null }
  | JobEvent

type Listener = (event: JobEvent) => void
const jobListeners = new Set<Listener>()

/** Подписка на события задач (прогресс импорта из Telegram и обработки файлов). */
export function onJobEvent(listener: Listener): () => void {
  jobListeners.add(listener)
  return () => jobListeners.delete(listener)
}

function invalidateEverything(qc: QueryClient): void {
  void qc.invalidateQueries()
}

class Batch {
  private dirty = new Set<string>()
  private timer: number | undefined

  constructor(private readonly qc: QueryClient) {}

  add(key: string): void {
    this.dirty.add(key)
    if (this.timer === undefined) this.timer = window.setTimeout(() => this.flush(), FLUSH_MS)
  }

  private flush(): void {
    this.timer = undefined
    const dirty = this.dirty
    this.dirty = new Set()
    const { qc } = this
    for (const type of dirty) {
      const resource = RESOURCE_OF[type]
      if (resource) void invalidateResource(qc, resource)
    }
    if (dirty.has('file') || dirty.has('attachment') || dirty.has('files')) {
      void qc.invalidateQueries({ queryKey: ['files'] })
      void qc.invalidateQueries({ queryKey: ['library'] })
      void qc.invalidateQueries({ queryKey: ['tg'] })
    }
    if (dirty.has('export')) void qc.invalidateQueries({ queryKey: ['exports'] })
    if (dirty.has('comment')) void qc.invalidateQueries({ queryKey: ['comments'] })
    if (dirty.has('tg')) void qc.invalidateQueries({ queryKey: ['tg'] })
    if (dirty.has('project')) void qc.invalidateQueries({ queryKey: ['project'] })
    if (dirty.has('user')) void qc.invalidateQueries({ queryKey: ['users'] })
    // Почти всё, что происходит в проекте, видно на дашборде и в ленте.
    void qc.invalidateQueries({ queryKey: ['dashboard'] })
    void qc.invalidateQueries({ queryKey: ['animatic'] })
    void qc.invalidateQueries({ queryKey: ['activity'] })
  }

  cancel(): void {
    if (this.timer !== undefined) window.clearTimeout(this.timer)
    this.timer = undefined
  }
}

export function useLiveUpdates(enabled: boolean): void {
  const qc = useQueryClient()

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') return undefined
    const batch = new Batch(qc)
    let source: EventSource | undefined
    let retryTimer: number | undefined
    let retryMs = RETRY_MIN_MS
    let lostConnection = false
    let closed = false

    const connect = () => {
      source = new EventSource('/api/events')
      source.onopen = () => {
        retryMs = RETRY_MIN_MS
        // Пока связи не было, мы могли пропустить события: перечитываем всё, что на экране.
        if (lostConnection) invalidateEverything(qc)
        lostConnection = false
      }
      source.onmessage = (message: MessageEvent<string>) => {
        let event: LiveEvent
        try {
          event = JSON.parse(message.data) as LiveEvent
        } catch {
          return
        }
        if (event.type === 'resync') invalidateEverything(qc)
        else if (event.type === 'activity') batch.add(event.entity_type)
        else if (event.type === 'tg') batch.add('tg')
        else if (event.type === 'job') {
          jobListeners.forEach((listener) => listener(event))
          if (event.job_type === 'tg_import') batch.add('tg')
          if (event.job_type === 'export') batch.add('export')
          if (event.status === 'done' || event.status === 'failed') batch.add('files')
        }
      }
      source.onerror = () => {
        lostConnection = true
        // Браузер сам переподключается, пока не получил ответ с ошибкой (например 401): тогда
        // поток закрыт насовсем, и повторять нужно вручную, с растущей паузой.
        if (source?.readyState === EventSource.CLOSED && !closed) {
          source.close()
          retryTimer = window.setTimeout(connect, retryMs)
          retryMs = Math.min(retryMs * 2, RETRY_MAX_MS)
        }
      }
    }

    // Мобильные браузеры рвут поток в фоне; при возврате на вкладку догоняем пропущенное.
    const onVisible = () => {
      if (document.visibilityState === 'visible') invalidateEverything(qc)
    }
    document.addEventListener('visibilitychange', onVisible)
    connect()

    return () => {
      closed = true
      document.removeEventListener('visibilitychange', onVisible)
      window.clearTimeout(retryTimer)
      batch.cancel()
      source?.close()
    }
  }, [enabled, qc])
}
