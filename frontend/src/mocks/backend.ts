import type { Command, CommandReply, RepoInfo, TaskView, WsMessage } from '../contracts/generated'

export interface CommandOutcome {
  /** Status HTTP que o gateway devolveria. */
  status: 200 | 409 | 422
  reply: CommandReply
}

/** O que os handlers MSW precisam de um "backend" (cenário vivo ou fixture estática). */
export interface MockBackend {
  readonly repos: readonly RepoInfo[]
  getView: () => TaskView | null
  /** Recebe cada `WsMessage` emitida. Retorna o unsubscribe. */
  subscribe: (listener: (msg: WsMessage) => void) => () => void
  handle: (command: Command) => CommandOutcome
  dispose: () => void
}
