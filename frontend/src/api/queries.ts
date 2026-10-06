import { queryOptions, useQuery } from '@tanstack/react-query'
import { fetchCurrentTask, fetchRepos, fetchUsage } from './client'

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

/** Uso da assinatura (cache do Claude Code). Atualiza a cada minuto; falha = sem chip. */
export const usageQuery = queryOptions({
  queryKey: ['usage'],
  queryFn: fetchUsage,
  refetchInterval: 60_000,
  retry: false,
})

export function useAccountUsage() {
  return useQuery(usageQuery)
}
