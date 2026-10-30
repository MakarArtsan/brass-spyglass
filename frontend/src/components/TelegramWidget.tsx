import { useEffect, useRef } from 'react'

declare global {
  interface Window {
    onTelegramAuth?: (user: Record<string, unknown>) => void
  }
}

/** Telegram Login Widget — запасной вход. Домен сайта должен быть задан у бота (BotFather /setdomain). */
export function TelegramWidget({ bot, onAuth }: { bot: string; onAuth: (data: Record<string, unknown>) => void }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    window.onTelegramAuth = onAuth
    const node = host.current
    if (!node) return
    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.dataset.telegramLogin = bot
    script.dataset.size = 'large'
    script.dataset.radius = '8'
    script.dataset.onauth = 'onTelegramAuth(user)'
    script.dataset.requestAccess = 'write'
    node.appendChild(script)
    return () => {
      node.replaceChildren()
      delete window.onTelegramAuth
    }
  }, [bot, onAuth])

  return <div ref={host} className="flex min-h-[48px] items-center justify-center" />
}
