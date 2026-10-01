import { queryOptions, useQuery } from '@tanstack/react-query'
import { fetchCurrentTask, fetchRepos, fetchWorkItems } from './client'

export const reposQuery = queryOptions({
  queryKey: ['repos'],
  queryFn: fetchRepos,
  staleTime: Infinity,
})

export const workItemsQuery = queryOptions({
  queryKey: ['azure', 'work-items'],
  queryFn: fetchWorkItems,
  staleTime: 30_000,
})

/** Re-hidratação do snapshot (ao abrir/reabrir o WS). Sempre busca; o resultado vai pro store. */
export const currentTaskQuery = queryOptions({
  queryKey: ['task'],
  queryFn: fetchCurrentTask,
  staleTime: 0,
})

export function useRepos() {
  return useQuery(reposQuery)
}

export function useWorkItems(enabled = true) {
  return useQuery({ ...workItemsQuery, enabled })
}
