import { FileUp, Loader2, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { toast } from '@/lib/toast'
import { cn } from '@/lib/utils'
import { ru } from '@/ru'

export interface SourceFile {
  name: string
  text: string
}

interface Props {
  files: SourceFile[]
  pasted: string
  checking: boolean
  onFiles: (files: SourceFile[]) => void
  onPasted: (text: string) => void
  onCheck: () => void
}

/** Шаг 2: один или несколько .json (части ответа LLM) либо текст ответа целиком в поле. */
export function SourceStep({ files, pasted, checking, onFiles, onPasted, onCheck }: Props) {
  const [over, setOver] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  const take = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    try {
      const read = await Promise.all(Array.from(list).map(async (f) => ({ name: f.name, text: await f.text() })))
      onFiles([...files, ...read])
    } catch {
      toast(ru.importPage.readFailed)
    }
    if (picker.current) picker.current.value = ''
  }

  const empty = files.length === 0 && pasted.trim() === ''

  return (
    <section aria-labelledby="import-step-2" className="space-y-4 rounded-2xl border border-line bg-chart/60 p-5">
      <h2 id="import-step-2" className="text-2xl">
        {ru.importPage.step2}
      </h2>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          void take(e.dataTransfer.files)
        }}
        className={cn(
          'flex flex-col items-center gap-2 rounded-xl border border-dashed p-5 text-center transition-colors duration-fast',
          over ? 'border-brass bg-brass/10' : 'border-line',
        )}
      >
        <FileUp size={24} className="text-brass" aria-hidden />
        <p className="text-sm">{ru.importPage.drop}</p>
        <Button type="button" variant="outline" onClick={() => picker.current?.click()}>
          {ru.importPage.pick}
        </Button>
        <input
          ref={picker}
          type="file"
          accept=".json,.txt,application/json,text/plain"
          multiple
          className="sr-only"
          aria-label={ru.importPage.pick}
          onChange={(e) => void take(e.target.files)}
        />
      </div>
      {files.length > 0 && (
        <ul className="space-y-1.5" aria-label={ru.importPage.loaded}>
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2 rounded-lg border border-line px-3 text-sm">
              <span className="min-w-0 flex-1 truncate py-2.5">{f.name}</span>
              <span className="mono text-xs text-fog">{Math.ceil(f.text.length / 1024)} КБ</span>
              <button
                type="button"
                aria-label={ru.importPage.removeFile(f.name)}
                onClick={() => onFiles(files.filter((_, n) => n !== i))}
                className="inline-flex min-h-touch min-w-touch items-center justify-center text-fog hover:text-paper"
              >
                <X size={16} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <label className="block">
        <span className="mb-1 block text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.importPage.paste}</span>
        <textarea
          value={pasted}
          onChange={(e) => onPasted(e.target.value)}
          rows={6}
          spellCheck={false}
          placeholder={ru.importPage.pastePlaceholder}
          className="mono w-full rounded-lg border border-line bg-ink p-3 text-xs text-paper outline-none focus:border-brass"
        />
        <span className="mt-1 block text-xs text-fog">{ru.importPage.pasteHint}</span>
      </label>
      <Button type="button" size="lg" disabled={empty || checking} onClick={onCheck} className="w-full sm:w-auto">
        {checking && <Loader2 size={18} className="animate-spin" aria-hidden />}
        {checking ? ru.importPage.checking : ru.importPage.check}
      </Button>
    </section>
  )
}
