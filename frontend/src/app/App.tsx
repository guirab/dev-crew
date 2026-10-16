import { lazy, Suspense } from 'react'
import { ChangesScreen } from '../changes/ChangesScreen'
import { Composer } from '../flow/Composer'
import { TaskScreen } from '../flow/TaskScreen'
import { HistoryList } from '../history/HistoryList'
import { isRunning, useCrewStore } from '../store/crew'
import { Backdrop } from './Backdrop'
import { Header } from './Header'
import { useAttentionNotification } from './notify'
import { ReconnectBanner } from './ReconnectBanner'
import { RunningTaskNotice } from './RunningTaskNotice'
import { useTabStatus } from './tabStatus'
import { cx } from '../lib/cx'
import styles from './App.module.css'

// Só existe no modo mock: `import.meta.env.MODE` é constante em build, então o bundle de
// produção nem inclui este chunk.
const DemoBar = import.meta.env.MODE === 'mock' ? lazy(() => import('../mocks/DemoBar')) : null

/** Layout: header + (nova tarefa | histórico | linha do tempo da tarefa | Alterações). Render puro do store; a conexão WS é montada em `main.tsx`. */
export function App() {
  const view = useCrewStore((s) => s.view)
  const screen = useCrewStore((s) => s.screen)
  useTabStatus(isRunning(view) || screen === 'task' || screen === 'changes' ? view : null)
  useAttentionNotification(view)
  const hydrated = useCrewStore((s) => s.hydrated)
  const connection = useCrewStore((s) => s.connection)
  // Sem snapshot ainda e WS tentando conectar: não pisca o formulário de nova tarefa.
  const ready = hydrated || connection === 'closed'
  const final = ready && screen === 'changes' ? (view?.final ?? null) : null

  return (
    <>
      <Backdrop animated={isRunning(view)} />
      <ReconnectBanner />
      <Header />
      <main className={cx(styles.wrap, final && styles.wide)} aria-busy={!ready}>
        {!ready ? (
          <p className={styles.status}>conectando…</p>
        ) : screen === 'history' ? (
          <HistoryList />
        ) : view && final ? (
          <ChangesScreen view={view} final={final} />
        ) : (screen === 'task' || screen === 'changes') && view ? (
          <TaskScreen view={view} />
        ) : (
          <>
            <RunningTaskNotice />
            <Composer />
          </>
        )}
      </main>
      {DemoBar && (
        <Suspense fallback={null}>
          <DemoBar />
        </Suspense>
      )}
    </>
  )
}
