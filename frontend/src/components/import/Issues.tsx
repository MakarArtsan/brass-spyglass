import { Copy, TriangleAlert, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { errorsForLlm, type ImportIssue } from '@/lib/scenarioImport'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

const line = (i: ImportIssue) => (i.where ? `${i.where}: ${i.message}` : i.message)

function List({ items, tone }: { items: ImportIssue[]; tone: 'error' | 'warning' | 'fix' }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((i, n) => (
        <li key={`${i.where}-${i.message}-${n}`} className="flex items-start gap-2">
          {tone === 'fix' ? (
            <Wrench size={14} className="mt-1 shrink-0 text-fog" aria-hidden />
          ) : (
            <TriangleAlert size={14} className={tone === 'error' ? 'mt-1 shrink-0 text-alert' : 'mt-1 shrink-0 text-status-in_progress'} aria-hidden />
          )}
          <span className={tone === 'fix' ? 'text-fog' : undefined}>{line(i)}</span>
        </li>
      ))}
    </ul>
  )
}

/** Замечания проверки: ошибки мешают создать проект, предупреждения и поправки — нет. */
export function Issues({ issues, defaultOpenWarnings = false }: { issues: ImportIssue[]; defaultOpenWarnings?: boolean }) {
  const errors = issues.filter((i) => i.level === 'error')
  const warnings = issues.filter((i) => i.level === 'warning')
  const fixes = issues.filter((i) => i.level === 'fix')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(errorsForLlm(issues))
      toast(ru.importPage.copied)
    } catch {
      toast(ru.importPage.copyFailed)
    }
  }

  return (
    <div className="space-y-4">
      {errors.length > 0 && (
        <div role="alert" className="space-y-3 rounded-xl border border-alert/50 bg-alert/5 p-4">
          <h3 className="text-lg text-alert">{ru.importPage.errors(errors.length)}</h3>
          <List items={errors} tone="error" />
          <Button type="button" variant="outline" onClick={copy}>
            <Copy size={16} aria-hidden />
            {ru.importPage.copyErrors}
          </Button>
          <p className="text-xs text-fog">{ru.importPage.copyErrorsHint}</p>
        </div>
      )}
      {warnings.length > 0 && (
        <details open={defaultOpenWarnings} className="rounded-xl border border-line p-3">
          <summary className="min-h-touch cursor-pointer text-sm font-semibold leading-[44px]">{ru.importPage.warnings(warnings.length)}</summary>
          <p className="mb-2 text-xs text-fog">{ru.importPage.warningsHint}</p>
          <List items={warnings} tone="warning" />
        </details>
      )}
      {fixes.length > 0 && (
        <details className="rounded-xl border border-line p-3">
          <summary className="min-h-touch cursor-pointer text-sm font-semibold leading-[44px]">{ru.importPage.fixes(fixes.length)}</summary>
          <p className="mb-2 text-xs text-fog">{ru.importPage.fixesHint}</p>
          <List items={fixes} tone="fix" />
        </details>
      )}
    </div>
  )
}
