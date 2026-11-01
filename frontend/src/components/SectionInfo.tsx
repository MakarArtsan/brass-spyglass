import { Info } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { NAV } from '@/nav'
import { ru } from '@/ru'

// Само окно подгружается при первом нажатии: на первый показ нужна только кнопка.
const SectionInfoDialog = lazy(() => import('@/components/SectionInfoDialog'))

/** Кнопка «i» у заголовка раздела: зачем он нужен и что в нём можно сделать. */
export function SectionInfo({ path }: { path: string }) {
  const [open, setOpen] = useState(false)
  const label = NAV.find((item) => item.path === path)?.label
  if (!label || !ru.info.sections[path]) return null
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={ru.info.button(label)}
        aria-haspopup="dialog"
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-fog outline-none transition-colors duration-fast hover:text-brass-light focus-visible:ring-2 focus-visible:ring-brass"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full border border-current">
          <Info size={16} aria-hidden />
        </span>
      </button>
      {open && (
        <Suspense fallback={null}>
          <SectionInfoDialog path={path} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
