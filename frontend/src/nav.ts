import {
  AudioLines,
  Clapperboard,
  Download,
  Film,
  Images,
  LayoutDashboard,
  ListChecks,
  ListTodo,
  Link2,
  Package,
  ScrollText,
  Send,
  Trash2,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { ru } from '@/ru'

export interface NavItem {
  path: string
  label: string
  icon: LucideIcon
  group: 'main' | 'service'
  /** Нужна способность пользователя (например, гость не видит журнал). */
  needs?: 'journal' | 'export'
  /** Пункт нижней панели телефона и её короткая подпись. */
  phone?: string
  stage: number
  note?: string
}

export const NAV: NavItem[] = [
  { path: '/', label: ru.nav.dashboard, icon: LayoutDashboard, group: 'main', phone: ru.nav.dashboard, stage: 2 },
  { path: '/scenes', label: ru.nav.scenes, icon: Clapperboard, group: 'main', stage: 1, note: ru.placeholder.scenes },
  { path: '/shots', label: ru.nav.shots, icon: ListChecks, group: 'main', phone: ru.nav.shotsShort, stage: 1, note: ru.placeholder.shots },
  { path: '/animatic', label: ru.nav.animatic, icon: Film, group: 'main', stage: 3, note: ru.placeholder.animatic },
  { path: '/assets', label: ru.nav.assets, icon: Package, group: 'main', stage: 1, note: ru.placeholder.assets },
  { path: '/media', label: ru.nav.media, icon: Images, group: 'main', phone: ru.nav.mediaShort, stage: 2, note: ru.placeholder.media },
  { path: '/setups', label: ru.nav.setups, icon: Link2, group: 'main', stage: 1, note: ru.placeholder.setups },
  { path: '/sound', label: ru.nav.sound, icon: AudioLines, group: 'main', stage: 1, note: ru.placeholder.sound },
  { path: '/tasks', label: ru.nav.tasks, icon: ListTodo, group: 'main', phone: ru.nav.tasks, stage: 1, note: ru.placeholder.tasks },
  { path: '/export', label: ru.nav.export, icon: Download, group: 'main', needs: 'export', stage: 3, note: ru.placeholder.export },
  { path: '/journal', label: ru.nav.journal, icon: ScrollText, group: 'service', needs: 'journal', stage: 1, note: ru.placeholder.journal },
  { path: '/team', label: ru.nav.team, icon: Users, group: 'service', stage: 0 },
  { path: '/telegram', label: ru.nav.telegram, icon: Send, group: 'service', stage: 2, note: ru.placeholder.telegram },
  { path: '/trash', label: ru.nav.trash, icon: Trash2, group: 'service', stage: 4, note: ru.placeholder.trash },
]

export const visibleNav = (abilities: { journal: boolean; export: boolean }) =>
  NAV.filter((i) => !i.needs || abilities[i.needs])
