import { lazy, Suspense } from 'react'
import { FlowColumn } from '../flow/FlowColumn'
import { HistoryList } from '../history/HistoryList'
import { isRunning, useCrewStore } from '../store/crew'
import { Backdrop } from './Backdrop'
import { Header } from './Header'
import { NowBar } from './NowBar'
import { ReconnectBanner } from './ReconnectBanner'
import { RunningTaskNotice } from './RunningTaskNotice'
import { useTabStatus } from './tabStatus'
import styles from './App.module.css'

// Só existe no modo mock: `import.meta.env.MODE` é constante em build, então o bundle de
// produção nem inclui este chunk.
const DemoBar = import.meta.env.MODE === 'mock' ? lazy(() => import('../mocks/DemoBar')) : null

/** Layout: header + fluxo vertical. Render puro do store; a conexão WS é montada em `main.tsx`. */
export function App() {
  const view = useCrewStore((s) => s.view)
  const screen = useCrewStore((s) => s.screen)
  useTabStatus(isRunning(view) || screen === 'task' ? view : null)
  const hydrated = useCrewStore((s) => s.hydrated)
  const connection = useCrewStore((s) => s.connection)
  // Sem snapshot ainda e WS tentando conectar: não pisca os cards de origem clicáveis.
  const ready = hydrated || connection === 'closed'

  return (
    <>
      <Backdrop animated={isRunning(view)} />
      <ReconnectBanner />
      <Header view={view} />
      <main className={styles.wrap} aria-busy={!ready}>
        {!ready ? (
          <p className={styles.status}>conectando…</p>
        ) : screen === 'history' ? (
          <HistoryList />
        ) : screen === 'task' && view ? (
          <>
            <NowBar view={view} />
            {/* key: cada tarefa começa com todos os cards fechados. */}
            <FlowColumn key={view.task_id} view={view} />
          </>
        ) : (
          <>
            <RunningTaskNotice />
            <FlowColumn key="none" view={null} />
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
