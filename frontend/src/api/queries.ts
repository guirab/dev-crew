import { queryOptions, useQuery } from '@tanstack/react-query'
import { fetchCurrentTask, fetchFolderProbe, fetchFolders, fetchRepos, fetchUsage } from './client'

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

export const foldersKey = ['folders'] as const
export const folderProbeKey = ['folder-probe'] as const

/** Subpastas do navegador de pastas. `path` undefined = pasta de projetos; `''` = unidades. */
export function foldersQuery(path: string | undefined) {
  return queryOptions({
    queryKey: [...foldersKey, path ?? null],
    queryFn: () => fetchFolders(path),
    staleTime: 0,
    retry: false,
  })
}

export function folderProbeQuery(path: string) {
  return queryOptions({
    queryKey: [...folderProbeKey, path],
    queryFn: () => fetchFolderProbe(path),
    staleTime: 0,
    retry: false,
  })
}
