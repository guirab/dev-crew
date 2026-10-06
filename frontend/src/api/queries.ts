import { queryOptions, useQuery } from '@tanstack/react-query'
import { fetchCurrentTask, fetchRepos } from './client'

export const reposQuery = queryOptions({
  queryKey: ['repos'],
  queryFn: fetchRepos,
  staleTime: Infinity,
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
