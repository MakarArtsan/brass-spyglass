import { useMe } from '@/hooks/useAuth'

interface Owned {
  created_by?: number | null
  uploaded_by?: { id: number } | null
}

/**
 * Что показывать пользователю по матрице ролей из ТЗ. Решает всё равно сервер: это лишь
 * способ не показывать кнопки, которые вернут 403.
 */
export function usePerms() {
  const { data } = useMe()
  const role = data?.user.role
  const meId = data?.user.id
  const privileged = role === 'owner' || role === 'director'
  const ownerOf = (x: Owned) => (x.created_by ?? x.uploaded_by?.id) === meId
  return {
    role,
    meId,
    /** Менять статус может любой, кроме гостя. */
    canStatus: role !== undefined && role !== 'guest',
    /** Править содержимое: владелец и режиссёр везде, «Команда» — только свои карточки. */
    canEdit: (x: Owned) => privileged || (role === 'team' && ownerOf(x)),
    canDelete: (x: Owned) => privileged || (role === 'team' && ownerOf(x)),
    /** Создавать карточки и загружать файлы. */
    canCreate: role !== undefined && role !== 'guest',
    canUpload: data?.abilities.upload ?? false,
    /** Порядок — это правка поля каждой карточки. */
    canReorder: privileged,
    canJournal: data?.abilities.journal ?? false,
  }
}
