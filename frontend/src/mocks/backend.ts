import type { Command, CommandReply, RepoInfo, TaskView, WsMessage } from '../contracts/generated'
import type { MockFolders } from './folders'

export interface CommandOutcome {
  /** Status HTTP que o gateway devolveria. */
  status: 200 | 409 | 422
  reply: CommandReply
}

/** O que os handlers MSW precisam de um "backend" (cenário vivo ou fixture estática). */
export interface MockBackend {
  /** Muda quando um `add_repo` é aceito. */
  readonly repos: readonly RepoInfo[]
  /** Disco fictício do navegador de pastas (`list`/`probe` devolvem `null` = o gateway responde 404). */
  readonly folders: MockFolders
  getView: () => TaskView | null
  /** Recebe cada `WsMessage` emitida. Retorna o unsubscribe. */
  subscribe: (listener: (msg: WsMessage) => void) => () => void
  handle: (command: Command) => CommandOutcome
  dispose: () => void
}
