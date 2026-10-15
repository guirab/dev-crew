import { create } from 'zustand'
import type { StageKey, TaskPhase } from '../contracts/aliases'
import type { LogLine, TaskView, WsProgress } from '../contracts/generated'
import type { FocusTarget } from '../app/nowStatus'

const TERMINAL_PHASES: readonly TaskPhase[] = ['done', 'cancelled', 'failed']

export type ConnectionState = 'connecting' | 'open' | 'closed'

export type Screen = 'new' | 'history' | 'task'

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
  /** Tela aberta: menu de origem (`new`), histórico ou o fluxo da tarefa. Sempre abre em `new`. */
  screen: Screen
  /** Pedido pra abrir e mostrar um card (CTA da faixa Agora). `seq` muda a cada clique, mesmo no mesmo alvo. */
  focus: { target: FocusTarget; seq: number } | null

  applyView: (view: TaskView | null) => void
  /** Aplica um snapshot vindo do REST só se nenhum snapshot chegou desde `sinceVersion`. */
  hydrate: (view: TaskView | null, sinceVersion: number) => void
  markHydrated: () => void
  applyProgress: (msg: WsProgress) => void
  setConnection: (connection: ConnectionState) => void
  setScreen: (screen: Screen) => void
  focusOn: (target: FocusTarget) => void
}

const initialState = {
  view: null,
  hydrated: false,
  viewVersion: 0,
  connection: 'connecting',
  progress: {},
  screen: 'new',
  focus: null,
} satisfies Partial<CrewState>

export const useCrewStore = create<CrewState>()((set) => ({
  ...initialState,

  applyView: (view) => {
    set((s) => ({ ...snapshot(s, view), hydrated: true }))
  },

  hydrate: (view, sinceVersion) => {
    set((s) =>
      s.viewVersion === sinceVersion
        ? { ...snapshot(s, view), hydrated: true }
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

  setScreen: (screen) => {
    set({ screen })
  },

  focusOn: (target) => {
    set((s) => ({ focus: { target, seq: (s.focus?.seq ?? 0) + 1 } }))
  },
}))

/**
 * Aplica um snapshot. Uma tarefa nova depois do primeiro snapshot (iniciada por qualquer origem)
 * abre o fluxo; o primeiro snapshot (abrir/recarregar) e a reconexão com a mesma tarefa não mexem na tela.
 */
function snapshot(
  s: Pick<CrewState, 'view' | 'hydrated' | 'viewVersion' | 'screen'>,
  view: TaskView | null,
): Pick<CrewState, 'view' | 'viewVersion' | 'progress' | 'screen'> {
  const started = s.hydrated && view !== null && view.task_id !== s.view?.task_id
  return {
    view,
    viewVersion: s.viewVersion + 1,
    progress: {},
    screen: started ? 'task' : s.screen,
  }
}

/** Tarefa em andamento: qualquer fase não terminal (inclui aguardando aprovação, escalada e limitada). */
export function isRunning(view: TaskView | null): view is TaskView {
  return view !== null && !TERMINAL_PHASES.includes(view.phase)
}

export function resetCrewStore(): void {
  useCrewStore.setState({ ...initialState })
}
