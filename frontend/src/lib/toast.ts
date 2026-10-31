/** Крошечная шина уведомлений: можно вызвать из любого места, в том числе из запросов. */
type Listener = (message: string) => void

const listeners = new Set<Listener>()

export function toast(message: string): void {
  listeners.forEach((l) => l(message))
}

export function onToast(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
