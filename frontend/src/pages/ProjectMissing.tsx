import { ru } from '@/ru'

/** Адрес проекта, которого нет или к которому нет доступа: ответ один и тот же (404). */
export default function ProjectMissing() {
  return (
    <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="font-display text-3xl">{ru.projects.missingTitle}</h1>
      <p className="max-w-md text-fog">{ru.projects.missingLead}</p>
      <a href="/" className="inline-flex min-h-touch items-center rounded-lg border border-line px-4 hover:border-brass/60">
        {ru.projects.toMine}
      </a>
    </div>
  )
}
