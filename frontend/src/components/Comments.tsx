import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Avatar } from '@/components/Avatar'
import { Button } from '@/components/ui/button'
import { usePerms } from '@/hooks/usePerms'
import { formatDateTime } from '@/lib/format'
import { useCommentMutations, useComments } from '@/lib/queries'
import { ru } from '@/ru'

/** Тред комментариев карточки. Комментировать могут все, включая гостя; удалять — свои. */
export function Comments({ entityType, entityId }: { entityType: string; entityId: number }) {
  const perms = usePerms()
  const { data } = useComments(entityType, entityId)
  const { add, remove } = useCommentMutations(entityType, entityId)
  const [text, setText] = useState('')

  const submit = () => {
    const body = text.trim()
    if (!body) return
    add.mutate(body, { onSuccess: () => setText('') })
  }

  return (
    <section aria-label={ru.comments.title} className="space-y-3">
      <h3 className="font-sans text-xs font-semibold uppercase tracking-[0.14em] text-fog">{ru.comments.title}</h3>
      {data?.length === 0 && <p className="text-sm text-fog">{ru.comments.empty}</p>}
      <ul className="space-y-3">
        {data?.map((c) => (
          <li key={c.id} className="flex gap-3">
            {c.author && <Avatar user={c.author} className="h-8 w-8" />}
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 text-xs text-fog">
                <span className="font-semibold text-paper">{c.author?.name ?? ru.journal.system}</span>
                <span>{formatDateTime(c.created_at)}</span>
                {perms.canDelete({ created_by: c.created_by }) && (
                  <button
                    type="button"
                    aria-label={ru.common.delete}
                    onClick={() => window.confirm(ru.comments.deleteConfirm) && remove.mutate(c.id)}
                    className="ml-auto flex min-h-touch min-w-touch items-center justify-center rounded text-fog hover:text-alert"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
              <p className="whitespace-pre-wrap break-words text-sm">{c.body}</p>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              submit()
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder={ru.comments.placeholder}
          aria-label={ru.comments.placeholder}
          className="min-h-touch flex-1 resize-y rounded-lg border border-line bg-ink px-3 py-2 text-sm outline-none focus:border-brass"
        />
        <Button type="button" onClick={submit} disabled={!text.trim() || add.isPending} className="self-end">
          {ru.comments.send}
        </Button>
      </div>
    </section>
  )
}
