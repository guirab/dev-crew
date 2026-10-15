import { queryOptions, useQuery } from '@tanstack/react-query'
import {
  fetchCurrentTask,
  fetchFileDiff,
  fetchFolderProbe,
  fetchFolders,
  fetchRepos,
  fetchTask,
  fetchTasks,
  fetchUsage,
} from './client'

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

/** Histórico de tarefas (`GET /api/tasks`). Sempre rebusca ao abrir a aba. */
export const tasksQuery = queryOptions({
  queryKey: ['tasks'],
  queryFn: fetchTasks,
  staleTime: 0,
  retry: false,
})

export function useTaskHistory() {
  return useQuery({ ...tasksQuery, refetchOnMount: 'always' })
}

/** Tarefa antiga aberta do Histórico. */
export function taskQuery(taskId: string) {
  return queryOptions({
    queryKey: ['tasks', taskId],
    queryFn: () => fetchTask(taskId),
    staleTime: 0,
    retry: false,
  })
}

/** Patch de um arquivo do resultado (`GET /api/tasks/<id>/diff`). */
export function fileDiffQuery(taskId: string, path: string) {
  return queryOptions({
    queryKey: ['diff', taskId, path],
    queryFn: () => fetchFileDiff(taskId, path),
    staleTime: 0,
    retry: false,
  })
}

/** Uso da assinatura (cache do Claude Code). Atualiza a cada minuto, mesmo com a janela atrás de outra. */
export const usageQuery = queryOptions({
  queryKey: ['usage'],
  queryFn: fetchUsage,
  refetchInterval: 60_000,
  refetchIntervalInBackground: true,
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
