import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, Copy, Loader2, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Logo } from '@/components/Logo'
import { StraitMap } from '@/components/StraitMap'
import { Button } from '@/components/ui/button'
import { sessionKey } from '@/hooks/useAuth'
import {
  api,
  ApiError,
  type AvailableChats,
  type NewProjectBody,
  type ProjectBrief,
  type SessionInfo,
} from '@/lib/api'
import { openProject } from '@/lib/project'
import { ru } from '@/ru'

const FIELD =
  'mt-1.5 min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-base normal-case tracking-normal text-paper outline-none focus:border-brass'
const LABEL = 'block text-xs font-semibold uppercase tracking-[0.14em] text-fog'
const STEP = 'font-display text-xl'

const today = (): string => new Date().toLocaleDateString('sv-SE') // ГГГГ-ММ-ДД в местном поясе

/** Новый проект: добавить помощника в свой чат, выбрать чат, назвать проект. Чат проверяет сервер. */
export default function NewProject() {
  const session = useQuery({ queryKey: sessionKey, queryFn: () => api<SessionInfo>('/session'), retry: false })
  const allowed = session.data?.can_create_projects === true
  // Чаты бота известны сразу, просмотр чатов помощника долгий: показываем первое, пока идёт второе.
  const quick = useQuery({
    queryKey: ['available-chats', 'quick'],
    queryFn: () => api<AvailableChats>('/projects/available-chats?userbot=false'),
    enabled: allowed,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
  const full = useQuery({
    queryKey: ['available-chats'],
    queryFn: () => api<AvailableChats>('/projects/available-chats'),
    enabled: allowed,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
  const early = quick.data && quick.data.chats.length > 0 ? quick.data : undefined
  const found = {
    data: full.data ?? early,
    error: full.error,
    isFetching: full.isFetching || quick.isFetching,
    refetch: () => Promise.all([quick.refetch(), full.refetch()]),
  }
  const [chatId, setChatId] = useState<number | null | undefined>(undefined)
  const [title, setTitle] = useState('')
  const [titleEn, setTitleEn] = useState('')
  const [deadline, setDeadline] = useState('')
  const [titleTouched, setTitleTouched] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (session.error instanceof ApiError && session.error.status === 401) window.location.replace('/login')
  }, [session.error])

  const create = useMutation({
    mutationFn: (body: NewProjectBody) => api<ProjectBrief>('/projects', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: (project) => openProject(project.slug),
    onError: (e) => setError(e instanceof ApiError ? e.message : ru.common.saveFailed),
  })

  const chats = found.data?.chats ?? []
  const superadmin = session.data?.is_superadmin === true
  const username = found.data?.userbot?.username ?? full.data?.userbot?.username
  const handle = username ? `@${username}` : null
  const botName = found.data?.bot?.username ?? quick.data?.bot?.username ?? full.data?.bot?.username
  const botHandle = botName ? `@${botName}` : null
  const hasBotChats = chats.some((c) => c.via === 'bot')

  const pick = (id: number | null) => {
    setChatId(id)
    const chat = chats.find((c) => c.id === id)
    if (chat && !titleTouched) setTitle(chat.title) // название чата — разумное начало названия проекта
  }

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      window.setTimeout(() => setCopied(null), 2000)
    } catch {
      /* буфер недоступен — имя видно на экране, его можно выделить */
    }
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    create.mutate({
      title: title.trim(),
      ...(titleEn.trim() && { title_en: titleEn.trim() }),
      ...(deadline && { deadline }),
      chat_id: chatId ?? null,
    })
  }

  const ready = title.trim() !== '' && chatId !== undefined && !create.isPending

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center overflow-hidden px-4 py-10">
      <StraitMap variant="page" className="absolute inset-0 h-full w-full opacity-90" />
      <div className="absolute inset-0 bg-gradient-to-b from-ink/60 via-ink/30 to-ink" aria-hidden />

      <main className="panel relative w-full max-w-xl p-6 shadow-2xl shadow-black/40 sm:p-8">
        <Logo className="mb-6" withTeam />
        <h1 className="font-display text-4xl leading-none">{ru.newProject.title}</h1>
        <p className="mt-3 text-sm text-fog">{ru.newProject.lead}</p>

        {session.isPending && (
          <p role="status" className="mt-6 text-fog">
            {ru.newProject.checking}
          </p>
        )}

        {session.data && !allowed && (
          <div className="mt-6 space-y-4">
            <p role="alert">{ru.newProject.notAllowed}</p>
            <Button asChild variant="outline">
              <a href="/">{ru.newProject.back}</a>
            </Button>
          </div>
        )}

        {allowed && (
          <form onSubmit={submit} className="mt-6 space-y-6">
            <section aria-labelledby="np-step-1" className="space-y-3">
              <h2 id="np-step-1" className={STEP}>
                {botHandle ? ru.newProject.stepChat : ru.newProject.stepChatHelper}
              </h2>
              {botHandle && (
                <div className="space-y-2 rounded-lg border border-line p-3">
                  <h3 className="text-sm font-semibold">{ru.newProject.viaBotTitle}</h3>
                  <p className="text-sm text-fog">
                    {ru.newProject.viaBotLead} <strong className="mono text-paper">{botHandle}</strong>,{' '}
                    {ru.newProject.viaBotSteps}
                  </p>
                  <p className="text-xs text-fog">{ru.newProject.viaBotNote}</p>
                  <div className="flex flex-wrap gap-3">
                    <Button type="button" variant="outline" onClick={() => void copy(botHandle)}>
                      {copied === botHandle ? <Check size={16} /> : <Copy size={16} />}
                      {copied === botHandle ? ru.newProject.copied : ru.newProject.copy}
                    </Button>
                    <Button type="button" variant="outline" onClick={() => void copy('/connect')}>
                      {copied === '/connect' ? <Check size={16} /> : <Copy size={16} />}
                      {copied === '/connect' ? ru.newProject.copied : ru.newProject.copyCommand}
                    </Button>
                  </div>
                </div>
              )}
              {(!botHandle || handle) && (
                <div className={botHandle ? 'space-y-2 rounded-lg border border-line p-3' : 'space-y-3'}>
                  {botHandle && <h3 className="text-sm font-semibold">{ru.newProject.viaUserbotTitle}</h3>}
                  <p className="text-sm text-fog">
                    {ru.newProject.botLead}{' '}
                    {handle ? <strong className="mono text-paper">{handle}</strong> : ru.newProject.botUnknown}{' '}
                    {ru.newProject.adminHint}
                  </p>
                  {handle && (
                    <Button type="button" variant="outline" onClick={() => void copy(handle)}>
                      {copied === handle ? <Check size={16} /> : <Copy size={16} />}
                      {copied === handle ? ru.newProject.copied : ru.newProject.copy}
                    </Button>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="button" variant="outline" onClick={() => void found.refetch()} disabled={found.isFetching}>
                  {found.isFetching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                  {found.isFetching ? ru.newProject.finding : ru.newProject.find}
                </Button>
                {full.isFetching && early && (
                  <span role="status" className="text-xs text-fog">
                    {ru.newProject.scanning}
                  </span>
                )}
              </div>
            </section>

            <section aria-labelledby="np-step-2" className="space-y-3">
              <h2 id="np-step-2" className={STEP}>
                {ru.newProject.stepPick}
              </h2>
              {found.data && !found.data.ready && (
                <p role="alert" className="text-sm text-alert">
                  {found.data.message ?? ru.app.error}
                </p>
              )}
              {found.data?.ready && found.data.message && chats.length > 0 && (
                <p className="text-xs text-fog">{found.data.message}</p>
              )}
              {found.error && (
                <p role="alert" className="text-sm text-alert">
                  {found.error instanceof ApiError ? found.error.message : ru.app.error}
                </p>
              )}
              {found.data?.ready && chats.length === 0 && !superadmin && (
                <p className="text-sm text-fog">{botHandle ? ru.newProject.noneBot : ru.newProject.none}</p>
              )}
              <div role="radiogroup" aria-labelledby="np-step-2" className="flex flex-col gap-2">
                {chats.map((chat) => (
                  <button
                    key={chat.id}
                    type="button"
                    role="radio"
                    aria-checked={chatId === chat.id}
                    onClick={() => pick(chat.id)}
                    className={`flex min-h-touch flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2 text-left transition-colors duration-fast ${
                      chatId === chat.id ? 'border-brass bg-chart text-paper' : 'border-line text-fog hover:border-brass/60 hover:text-paper'
                    }`}
                  >
                    <span aria-hidden className={`h-3 w-3 shrink-0 rounded-full border ${chatId === chat.id ? 'border-brass bg-brass' : 'border-line'}`} />
                    <span className="min-w-0 flex-1">{chat.title}</span>
                    {hasBotChats && chat.via && (
                      <span className="rounded-full border border-line px-2 py-0.5 text-[11px] uppercase tracking-wide text-fog">
                        {chat.via === 'bot' ? ru.newProject.viaBot : ru.newProject.viaUserbot}
                      </span>
                    )}
                    {chat.via === 'bot' && chat.bot_admin === false && (
                      <span className="basis-full pl-6 text-xs text-status-in_progress">{ru.newProject.botNotAdmin}</span>
                    )}
                  </button>
                ))}
                {superadmin && (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={chatId === null}
                    onClick={() => pick(null)}
                    className={`flex min-h-touch items-center gap-3 rounded-lg border border-dashed px-4 text-left transition-colors duration-fast ${
                      chatId === null ? 'border-brass bg-chart text-paper' : 'border-line text-fog hover:border-brass/60 hover:text-paper'
                    }`}
                  >
                    <span aria-hidden className={`h-3 w-3 shrink-0 rounded-full border ${chatId === null ? 'border-brass bg-brass' : 'border-line'}`} />
                    {ru.newProject.noChat}
                  </button>
                )}
              </div>
            </section>

            <section aria-labelledby="np-step-3" className="space-y-3">
              <h2 id="np-step-3" className={STEP}>
                {ru.newProject.stepDetails}
              </h2>
              <label className={LABEL}>
                {ru.newProject.titleLabel}
                <input
                  required
                  maxLength={200}
                  value={title}
                  onChange={(e) => {
                    setTitle(e.target.value)
                    setTitleTouched(true)
                  }}
                  className={FIELD}
                />
              </label>
              <label className={LABEL}>
                {ru.newProject.titleEnLabel}
                <input maxLength={200} value={titleEn} onChange={(e) => setTitleEn(e.target.value)} className={FIELD} />
              </label>
              <label className={LABEL}>
                {ru.newProject.deadlineLabel}
                <input type="date" min={today()} value={deadline} onChange={(e) => setDeadline(e.target.value)} className={FIELD} />
              </label>
              <p className="text-xs text-fog">{ru.newProject.deadlineHint}</p>
            </section>

            {error && (
              <p role="alert" className="text-sm text-alert">
                {error}
              </p>
            )}
            <div className="flex flex-wrap justify-between gap-3">
              <Button asChild variant="ghost">
                <a href="/">{ru.newProject.back}</a>
              </Button>
              <Button type="submit" size="lg" disabled={!ready}>
                {create.isPending ? ru.newProject.submitting : ru.newProject.submit}
              </Button>
            </div>
          </form>
        )}
      </main>
    </div>
  )
}
