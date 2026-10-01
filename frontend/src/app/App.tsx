import type { TaskView } from '../contracts/generated'

// Placeholder from M0. Stream C replaces this with the flow UI (see plan/04-frontend.md).
export function App({ view = null }: { view?: TaskView | null }) {
  return <main>dev-crew — {view ? view.title : 'sem tarefa'}</main>
}
