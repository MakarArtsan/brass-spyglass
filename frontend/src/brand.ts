/**
 * Единственное место, где живут цвета, шрифты и тексты бренда (ТЗ, «Бренд и дизайн»).
 * Tailwind берёт токены отсюда (tailwind.config.ts), в компонентах захардкоженных значений нет.
 */

export type Theme = 'dark' | 'light'

/** Токены палитры. Тёмная тема по умолчанию, светлая — переключатель. */
export const palette = {
  dark: {
    ink: '#0E1420', // фон: глубокий ночной синий
    chart: '#161E2E', // карточки и панели
    brass: '#C9A24A', // главный акцент, кнопки, прогресс
    'brass-light': '#E8C979', // ховеры, блики
    north: '#5FA8B8', // метки Севера: холодная бирюза
    south: '#D9774B', // метки Юга: терракота
    fog: '#8A94A6', // вторичный текст
    // Добавлено сверх списка ТЗ — без них нет основного текста, линий и тревог:
    paper: '#ECE6D6', // основной текст
    line: '#26324A', // границы и разделители
    alert: '#E5584B', // просрочки, красный отсчёт
    'on-brass': '#0E1420', // текст на латунной кнопке
  },
  light: {
    ink: '#F3EEE1',
    chart: '#FFFCF5',
    brass: '#8F6B14',
    'brass-light': '#B38A25',
    north: '#2D7C8E',
    south: '#B4552A',
    fog: '#5A6477',
    paper: '#18202F',
    line: '#D9D1BD',
    alert: '#C23A2E',
    'on-brass': '#FFFCF5',
  },
} as const satisfies Record<Theme, Record<string, string>>

export type ColorToken = keyof (typeof palette)['dark']

/** Статусы как в Excel-трекере: цвет строки/карточки и чипа. */
export const statusColors = {
  dark: {
    not_started: '#7C8597', // серый
    in_progress: '#E3B93C', // жёлтый
    review: '#5B8DEF', // синий
    rework: '#E4663F', // оранжево-красный
    done: '#5DAA6E', // зелёный
    cut: '#6A7385', // серый, текст зачёркнут
  },
  light: {
    not_started: '#6B7487',
    in_progress: '#A97F0B',
    review: '#2F62C9',
    rework: '#BF4421',
    done: '#2F7F43',
    cut: '#7A8396',
  },
} as const satisfies Record<Theme, Record<string, string>>

export type StatusKey = keyof (typeof statusColors)['dark']
export const STATUS_ORDER: StatusKey[] = [
  'not_started',
  'in_progress',
  'review',
  'rework',
  'done',
  'cut',
]

export const fonts = {
  display: "'Cormorant Garamond', Georgia, serif", // заголовки и название фильма, 600
  sans: "'Manrope Variable', system-ui, sans-serif", // интерфейс
  mono: "'JetBrains Mono Variable', ui-monospace, monospace", // таймкоды, ID шотов, длительности
} as const

/** Название и логотип команды пока неизвестны (ТЗ, «Открытые вопросы»): плейсхолдер. */
export const TEAM_NAME = 'Команда проекта'
export const TEAM_LOGO: string | null = null

/** Бейдж конкурса. Логотипы саммита и Seedance — только после сверки с их брендгайдом. */
export const CONTEST_BADGE = 'Entry · 1 Billion AI Film Award 2027'

export const FILM = {
  title: 'Битва при кривом зеркале',
  titleEn: 'The Brass Spyglass',
} as const

/** Отсчёт до дедлайна: латунный за 7 дней, красный за 3 (ТЗ). */
export const COUNTDOWN = { brassDays: 7, alertDays: 3 } as const

/** Движение: Framer Motion, 150–250 мс, без «прыгающих» анимаций. */
export const motion = {
  fast: 0.15,
  base: 0.2,
  slow: 0.25,
  ease: [0.2, 0, 0, 1] as [number, number, number, number],
} as const

/** Раскладки: ПК от 1024 px, смартфон до 768 px; между ними — раскладка смартфона. */
export const breakpoints = { desktop: 1024 } as const

/** Минимальная область касания, px. */
export const TOUCH_TARGET = 44
