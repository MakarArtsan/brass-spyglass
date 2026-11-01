import { Hourglass } from 'lucide-react'
import { SectionInfo } from '@/components/SectionInfo'
import { Navigate } from 'react-router-dom'
import { useMe } from '@/hooks/useAuth'
import { NAV } from '@/nav'
import { ru } from '@/ru'

/** Раздел, который появится на следующих этапах. Кроме прав: гость не открывает журнал по прямой ссылке. */
export default function Placeholder({ path }: { path: string }) {
  const { data: me } = useMe()
  const item = NAV.find((i) => i.path === path)
  if (!item) return null
  if (item.needs && me && !me.abilities[item.needs]) return <Navigate to="/" replace />
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center gap-4 py-16 text-center">
      <item.icon className="text-brass" size={40} aria-hidden />
      <div className="flex items-center gap-1">
        <h1 className="text-4xl">{item.label}</h1>
        <SectionInfo path={path} />
      </div>
      {item.note && <p className="text-fog">{item.note}</p>}
      <p className="mono inline-flex items-center gap-2 rounded-full border border-line px-4 py-1.5 text-xs uppercase tracking-wider text-fog">
        <Hourglass size={14} aria-hidden />
        {ru.placeholder.soon} {item.stage}
      </p>
    </section>
  )
}
