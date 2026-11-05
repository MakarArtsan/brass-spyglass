import { Download } from 'lucide-react'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Avatar } from '@/components/Avatar'
import { Issues } from '@/components/import/Issues'
import { PreviewPanel } from '@/components/import/PreviewPanel'
import { PromptStep } from '@/components/import/PromptStep'
import { SourceStep, type SourceFile } from '@/components/import/SourceStep'
import { PageHeader } from '@/components/PageHeader'
import { useMe, useProject } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { paramsOf, sourceUrl, useApplyImport, useCheckImport, useImportRuns, type ImportCheck, type PromptForm } from '@/lib/scenarioImport'
import { toast } from '@/lib/toast'
import { ru } from '@/ru'

const DEFAULT_SHOT_SEC = 15

/** Импорт сценария: промпт для LLM → файл с ответом → проверка и предпросмотр → создание карточек. */
export default function ImportScenario() {
  const { data: me } = useMe()
  const { data: project } = useProject()
  const navigate = useNavigate()
  const runs = useImportRuns()
  const check = useCheckImport()
  const apply = useApplyImport()

  const [form, setForm] = useState<PromptForm>({ min: '', max: '', shot: '', language: 'en' })
  const [files, setFiles] = useState<SourceFile[]>([])
  const [pasted, setPasted] = useState('')
  const [result, setResult] = useState<ImportCheck | null>(null)
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  if (me && !me.abilities.import_scenario) return <Navigate to="/" replace />

  const texts = () => [...files.map((f) => f.text), ...(pasted.trim() ? [pasted] : [])]
  const names = () => [...files.map((f) => f.name), ...(pasted.trim() ? [ru.importPage.pastedName] : [])]
  const params = paramsOf(form)

  const reset = () => {
    setResult(null)
    setExcluded(new Set())
  }

  const runCheck = () =>
    check.mutate(
      { ...params, texts: texts() },
      {
        onSuccess: (data) => {
          setResult(data)
          // «Не импортировать» переживает повторную проверку, пока такой код ещё есть в файле.
          const codes = new Set([...(data.preview?.characters ?? []), ...(data.preview?.locations ?? []), ...(data.preview?.assets ?? [])].map((c) => c.code))
          setExcluded((old) => new Set([...old].filter((c) => codes.has(c))))
        },
        onError: (e) => toast(e instanceof ApiError ? e.message : ru.importPage.checkFailed),
      },
    )

  const create = () =>
    apply.mutate(
      { ...params, texts: texts(), exclude: [...excluded], names: names() },
      {
        onSuccess: (data) => {
          toast(ru.importPage.created(data.created.scene ?? 0, data.created.shot ?? 0, data.created.asset ?? 0))
          navigate('/')
        },
        onError: (e) => {
          toast(e instanceof ApiError ? e.message : ru.importPage.createFailed)
          if (e instanceof ApiError && e.status === 409) runCheck() // проект успели заполнить: покажем причину
        },
      },
    )

  const toggle = (code: string) =>
    setExcluded((old) => {
      const next = new Set(old)
      if (!next.delete(code)) next.add(code)
      return next
    })

  return (
    <section>
      <PageHeader title={ru.importPage.title} lead={ru.importPage.lead} />
      <div className="space-y-6">
        <PromptStep
          form={form}
          onChange={setForm}
          defaults={{ min: project?.target_min_sec ?? 300, max: project?.target_max_sec ?? 420, shot: DEFAULT_SHOT_SEC }}
        />
        <SourceStep
          files={files}
          pasted={pasted}
          checking={check.isPending}
          onFiles={(next) => {
            setFiles(next)
            reset()
          }}
          onPasted={(text) => {
            setPasted(text)
            reset()
          }}
          onCheck={runCheck}
        />
        {result && (
          <div className="space-y-4" aria-live="polite">
            {result.issues.length > 0 && <Issues issues={result.issues} />}
            {result.ok && result.issues.length === 0 && (
              <p className="text-sm text-status-done">{ru.importPage.allGood}</p>
            )}
            {result.preview && (
              <PreviewPanel
                preview={result.preview}
                canApply={result.can_apply}
                notEmptyReason={result.not_empty_reason}
                excluded={excluded}
                creating={apply.isPending}
                onToggle={toggle}
                onCreate={create}
              />
            )}
          </div>
        )}
        {runs.data && runs.data.length > 0 && (
          <section aria-labelledby="import-history">
            <h2 id="import-history" className="mb-3 text-2xl">
              {ru.importPage.history}
            </h2>
            <ul className="space-y-2">
              {runs.data.map((run) => (
                <li key={run.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-line bg-chart p-3">
                  {run.created_by && <Avatar user={run.created_by} className="h-8 w-8" />}
                  <div className="min-w-0 flex-1 text-sm">
                    <div className="font-semibold">{ru.importPage.historyLine(run.created.scene ?? 0, run.created.shot ?? 0, run.created.asset ?? 0)}</div>
                    <div className="text-xs text-fog">
                      {formatDateTime(run.created_at)} · {run.created_by?.name ?? ru.journal.system}
                      {run.filename ? ` · ${run.filename}` : ''}
                    </div>
                  </div>
                  <a href={sourceUrl(run.id)} download className="inline-flex min-h-touch items-center gap-2 text-sm text-brass hover:text-brass-light">
                    <Download size={16} aria-hidden />
                    {ru.importPage.source}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </section>
  )
}
