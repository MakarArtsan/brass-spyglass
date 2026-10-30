import { Countdown } from '@/components/Countdown'
import { Lens } from '@/components/Lens'
import { StatusChip } from '@/components/StatusChip'
import { StraitMap } from '@/components/StraitMap'
import { palette, STATUS_ORDER, fonts } from '@/brand'
import { ru } from '@/ru'

/** Образец кадра для линзы: пролив, два острова и туман — собран из токенов палитры. */
const c = palette.dark
const sample =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
<defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.chart}"/><stop offset=".55" stop-color="${c.fog}"/><stop offset="1" stop-color="${c.ink}"/></linearGradient></defs>
<rect width="200" height="200" fill="url(#s)"/>
<path d="M0 118 Q40 98 70 112 T130 106 T200 114 V200 H0Z" fill="${c.ink}" opacity=".85"/>
<path d="M18 120 Q40 80 66 118Z" fill="${c.north}"/><path d="M118 118 Q150 70 182 118Z" fill="${c.south}"/>
<circle cx="100" cy="60" r="16" fill="${c['brass-light']}" opacity=".9"/>
<path d="M0 150 H200 M0 168 H200" stroke="${c.paper}" stroke-opacity=".25"/></svg>`)

const day = 86_400_000
const inDays = (d: number) => new Date(Date.now() + d * day + 3_600_000).toISOString()

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-2xl">{title}</h2>
      {children}
    </section>
  )
}

/** Витрина бренда для проверки токенов, шрифтов и фирменных деталей. В навигации не показывается. */
export default function Brand() {
  return (
    <div className="space-y-10">
      <h1 className="text-4xl">{ru.brand.title}</h1>

      <Section title={ru.brand.palette}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          {Object.keys(palette.dark).map((name) => (
            <div key={name} className="panel overflow-hidden">
              <div className="h-14 border-b border-line" style={{ backgroundColor: `rgb(var(--${name}))` }} />
              <div className="p-2">
                <div className="mono text-xs font-semibold">{name}</div>
                <div className="mono text-[11px] text-fog">{palette.dark[name as keyof typeof palette.dark]}</div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title={ru.brand.fonts}>
        <div className="panel space-y-3 p-5">
          <p className="font-display text-4xl font-semibold">{fonts.display.split(',')[0].replaceAll("'", '')} — Битва при кривом зеркале</p>
          <p className="font-sans text-base">Manrope — интерфейс: Список шотов, статусы, комментарии и кнопки.</p>
          <p className="mono text-base">JetBrains Mono — 01.03 · CH-01 · SND-01 · 00:05:12 · 12.5 сек</p>
        </div>
      </Section>

      <Section title={ru.brand.statuses}>
        <div className="flex flex-wrap gap-2">
          {STATUS_ORDER.map((s) => (
            <StatusChip key={s} status={s} />
          ))}
        </div>
      </Section>

      <Section title={ru.brand.lens}>
        <p className="text-sm text-fog">{ru.brand.lensHint}</p>
        <div className="flex flex-wrap items-center gap-8 py-3">
          <Lens src={sample} alt="Север и Юг" size={140} />
          <Lens src={sample} alt="Север и Юг" size={96} />
          <Lens src={sample} alt="Север и Юг" size={64} />
        </div>
      </Section>

      <Section title={ru.brand.countdown}>
        <div className="panel flex flex-wrap gap-8 p-5">
          <Countdown target={inDays(18)} label="> 7 дней" />
          <Countdown target={inDays(5)} label="≤ 7 дней" />
          <Countdown target={inDays(2)} label="≤ 3 дней" />
        </div>
      </Section>

      <Section title={ru.brand.map}>
        <div className="panel relative h-36 overflow-hidden">
          <StraitMap className="absolute inset-0 h-full w-full" />
        </div>
        <div className="panel relative h-72 overflow-hidden">
          <StraitMap variant="page" className="absolute inset-0 h-full w-full" />
        </div>
      </Section>
    </div>
  )
}
