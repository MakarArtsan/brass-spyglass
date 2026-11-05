import { ClipboardCopy, Download, FileJson } from 'lucide-react'
import { Button, buttonVariants } from '@/components/ui/button'
import { exampleUrl, fetchPrompt, paramsOf, promptUrl, type PromptForm } from '@/lib/scenarioImport'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-fog">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-fog">{hint}</span>}
    </label>
  )
}

const input = 'mono min-h-touch w-full rounded-lg border border-line bg-ink px-3 text-sm text-paper outline-none focus:border-brass'

/** Шаг 1: параметры фильма и промпт, который человек отдаёт своей LLM вместе со сценарием. */
export function PromptStep({
  form,
  defaults,
  onChange,
}: {
  form: PromptForm
  /** Что подставит сервер, если поле пустое: цели проекта и лимит шота. */
  defaults: { min: number; max: number; shot: number }
  onChange: (next: PromptForm) => void
}) {
  const set = (key: keyof PromptForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...form, [key]: e.target.value })
  const params = paramsOf(form)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(await fetchPrompt(params, form.language))
      toast(ru.importPage.copied)
    } catch {
      toast(ru.importPage.copyFailed)
    }
  }

  return (
    <section aria-labelledby="import-step-1" className="space-y-4 rounded-2xl border border-line bg-chart/60 p-5">
      <h2 id="import-step-1" className="text-2xl">
        {ru.importPage.step1}
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label={ru.importPage.min}>
          <input inputMode="numeric" value={form.min} placeholder={String(defaults.min)} onChange={set('min')} className={input} />
        </Field>
        <Field label={ru.importPage.max}>
          <input inputMode="numeric" value={form.max} placeholder={String(defaults.max)} onChange={set('max')} className={input} />
        </Field>
        <Field label={ru.importPage.shot}>
          <input inputMode="decimal" value={form.shot} placeholder={String(defaults.shot)} onChange={set('shot')} className={input} />
        </Field>
        <Field label={ru.importPage.language}>
          <select value={form.language} onChange={set('language')} className={cn(input, 'font-sans')}>
            {Object.entries(ru.importPage.languages).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <p className="text-xs text-fog">{ru.importPage.paramsHint}</p>
      <div className="flex flex-wrap gap-3">
        <a href={promptUrl(params, form.language)} download="import-prompt.md" className={buttonVariants()}>
          <Download size={16} aria-hidden />
          {ru.importPage.download}
        </a>
        <Button type="button" variant="outline" onClick={copy}>
          <ClipboardCopy size={16} aria-hidden />
          {ru.importPage.copy}
        </Button>
        <a href={exampleUrl()} download="project-example.json" className={buttonVariants({ variant: 'ghost' })}>
          <FileJson size={16} aria-hidden />
          {ru.importPage.example}
        </a>
      </div>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-fog">
        {ru.importPage.howTo.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
    </section>
  )
}
