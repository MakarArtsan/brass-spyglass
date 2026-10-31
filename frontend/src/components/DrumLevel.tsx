import { cn } from '@/lib/utils'
import { ru } from '@/ru'

/** Уровень барабана 0–5: пять столбиков, заполняются латунью. */
export function DrumLevel({ level }: { level: number | null }) {
  const value = level ?? 0
  return (
    <span className="inline-flex items-end gap-0.5" role="img" aria-label={`${ru.scenes.drum}: ${value} из 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} aria-hidden className={cn('w-1.5 rounded-sm', i <= value ? 'bg-brass' : 'bg-line')} style={{ height: 6 + i * 3 }} />
      ))}
    </span>
  )
}
