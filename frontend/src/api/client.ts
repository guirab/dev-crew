import type { Command, CommandReply, RepoInfo, TaskView } from '../contracts/generated'
import { isCommandReply, isNullableTaskView, isRepoList } from './guards'

/** Erro de chamada ao gateway. `status` 0 = sem resposta (rede/servidor fora). */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Erro de `POST /api/commands` (409 = tarefa ativa/estado inválido, 422 = validação). */
export class CommandError extends ApiError {
  constructor(message: string, status: number) {
    super(message, status)
    this.name = 'CommandError'
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init)
  } catch {
    throw new ApiError('Sem conexão com o servidor.', 0)
  }
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return undefined
  }
}

async function getJson<T>(path: string, guard: (v: unknown) => v is T): Promise<T> {
  const res = await send(path)
  const body = await readJson(res)
  if (!res.ok) throw new ApiError(`Falha ao carregar (${res.status}).`, res.status)
  if (!guard(body)) throw new ApiError('Resposta inesperada do servidor.', res.status)
  return body
}

export function fetchRepos(): Promise<RepoInfo[]> {
  return getJson('/api/repos', isRepoList)
}

export function fetchCurrentTask(): Promise<TaskView | null> {
  return getJson('/api/task', isNullableTaskView)
}

function errorFromBody(body: unknown, status: number): string {
  if (isCommandReply(body) && body.error) return body.error
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const { detail } = body
    if (typeof detail === 'string') return detail
  }
  return `Comando recusado (${status}).`
}

/** Envia um comando. Resolve só com `ok: true`; qualquer recusa vira `CommandError`. */
export async function postCommand(command: Command): Promise<CommandReply> {
  let res: Response
  try {
    res = await send('/api/commands', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(command),
    })
  } catch (error) {
    throw new CommandError(error instanceof Error ? error.message : 'Falha de rede.', 0)
  }
  const body = await readJson(res)
  if (!res.ok) throw new CommandError(errorFromBody(body, res.status), res.status)
  if (!isCommandReply(body)) throw new CommandError('Resposta inesperada do servidor.', res.status)
  if (!body.ok) throw new CommandError(body.error ?? 'Comando recusado.', res.status)
  return body
}
