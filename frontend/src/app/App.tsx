import { lazy, Suspense } from 'react'
import { FlowColumn } from '../flow/FlowColumn'
import { selectActiveView, useCrewStore } from '../store/crew'
import { Header } from './Header'
import { ReconnectBanner } from './ReconnectBanner'
import { useTabStatus } from './tabStatus'
import styles from './App.module.css'

// Só existe no modo mock: `import.meta.env.MODE` é constante em build, então o bundle de
// produção nem inclui este chunk.
const DemoBar = import.meta.env.MODE === 'mock' ? lazy(() => import('../mocks/DemoBar')) : null

/** Layout: header + fluxo vertical. Render puro do store; a conexão WS é montada em `main.tsx`. */
export function App() {
  const view = useCrewStore(selectActiveView)
  useTabStatus(view)
  const hydrated = useCrewStore((s) => s.hydrated)
  const connection = useCrewStore((s) => s.connection)
  // Sem snapshot ainda e WS tentando conectar: não pisca os cards de origem clicáveis.
  const ready = hydrated || connection === 'closed'

  return (
    <>
      <ReconnectBanner />
      <Header view={view} />
      <main className={styles.wrap} aria-busy={!ready}>
        {ready ? (
          // key: cada tarefa começa com todos os cards fechados.
          <FlowColumn key={view?.task_id ?? 'none'} view={view} />
        ) : (
          <p className={styles.status}>conectando…</p>
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
