import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type Me, type Project, type User } from '@/lib/api'

export const meKey = ['me'] as const

export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: () => api<Me>('/me'),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 60_000,
  })
}

export function useProject() {
  return useQuery({ queryKey: ['project'], queryFn: () => api<Project>('/project'), staleTime: 60_000 })
}

export function useUsers() {
  return useQuery({ queryKey: ['users'], queryFn: () => api<User[]>('/users') })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      qc.clear()
      window.location.assign('/login')
    },
  })
}
