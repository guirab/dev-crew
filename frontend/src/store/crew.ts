import { create } from 'zustand'
import type { StageKey } from '../contracts/aliases'
import type { LogLine, TaskView, WsProgress } from '../contracts/generated'

export type ConnectionState = 'connecting' | 'open' | 'closed'

const MAX_PROGRESS_LINES = 50

interface CrewState {
  /** Último snapshot do orquestrador. `null` = sem tarefa. A UI só renderiza isto. */
  view: TaskView | null
  /** Já recebemos um primeiro snapshot (WS ou REST)? */
  hydrated: boolean
  /** Incrementa a cada snapshot aplicado; protege contra respostas REST atrasadas. */
  viewVersion: number
  connection: ConnectionState
  /** Linhas de progresso entre snapshots. O snapshot seguinte é a verdade e as descarta. */
  progress: Partial<Record<StageKey, LogLine[]>>
  /** Tarefa terminal que o usuário dispensou com "Nova tarefa" (decisão só de UI). */
  dismissedTaskId: string | null

  applyView: (view: TaskView | null) => void
  /** Aplica um snapshot vindo do REST só se nenhum snapshot chegou desde `sinceVersion`. */
  hydrate: (view: TaskView | null, sinceVersion: number) => void
  markHydrated: () => void
  applyProgress: (msg: WsProgress) => void
  setConnection: (connection: ConnectionState) => void
  dismissTask: () => void
}

const initialState = {
  view: null,
  hydrated: false,
  viewVersion: 0,
  connection: 'connecting',
  progress: {},
  dismissedTaskId: null,
} satisfies Partial<CrewState>

export const useCrewStore = create<CrewState>()((set) => ({
  ...initialState,

  applyView: (view) => {
    set((s) => ({ view, hydrated: true, viewVersion: s.viewVersion + 1, progress: {} }))
  },

  hydrate: (view, sinceVersion) => {
    set((s) =>
      s.viewVersion === sinceVersion
        ? { view, hydrated: true, viewVersion: s.viewVersion + 1, progress: {} }
        : { hydrated: true },
    )
  },

  markHydrated: () => {
    set({ hydrated: true })
  },

  applyProgress: (msg) => {
    set((s) => {
      if (s.view?.task_id !== msg.task_id) return s
      const line: LogLine = { ts: new Date().toISOString(), text: msg.data.text }
      const lines = [...(s.progress[msg.data.agent] ?? []), line].slice(-MAX_PROGRESS_LINES)
      return { progress: { ...s.progress, [msg.data.agent]: lines } }
    })
  },

  setConnection: (connection) => {
    set({ connection })
  },

  dismissTask: () => {
    set((s) => ({ dismissedTaskId: s.view?.task_id ?? null }))
  },
}))

/** Tarefa visível: o snapshot, a menos que o usuário tenha dispensado essa tarefa terminal. */
export function selectActiveView(s: Pick<CrewState, 'view' | 'dismissedTaskId'>): TaskView | null {
  return s.view && s.view.task_id !== s.dismissedTaskId ? s.view : null
}

export function resetCrewStore(): void {
  useCrewStore.setState({ ...initialState })
}
