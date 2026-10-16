import { useCrewStore } from '../store/crew'
import { Button } from '../ui/Button'
import { useNotificationPermission } from './notify'
import styles from './Header.module.css'
import { UsageChip } from './UsageChip'

/** Marca, abas (Tarefa, Histórico), uso da assinatura e "+ Nova". O estado da tarefa fica no nó que pede você. */
export function Header() {
  const screen = useCrewStore((s) => s.screen)
  const setScreen = useCrewStore((s) => s.setScreen)
  const hasTask = useCrewStore((s) => s.view !== null)
  const [permission, askPermission] = useNotificationPermission()

  return (
    <header className={styles.header}>
      <h1 className={styles.brand}>
        <span className={styles.prompt}>&gt;</span> dev-crew
        <span className={styles.caret} aria-hidden="true" />
      </h1>
      <div role="tablist" aria-label="Seções" className={styles.tabs}>
        <button
          type="button"
          role="tab"
          aria-selected={screen !== 'history'}
          className={styles.tab}
          onClick={() => {
            setScreen(hasTask ? 'task' : 'new')
          }}
        >
          Tarefa
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={screen === 'history'}
          className={styles.tab}
          onClick={() => {
            setScreen('history')
          }}
        >
          Histórico
        </button>
      </div>
      <span className={styles.sp} />
      {permission === 'default' && (
        <Button
          variant="link"
          title="Avisar no Windows quando a tarefa precisar de você ou terminar"
          onClick={askPermission}
        >
          ativar avisos
        </Button>
      )}
      <UsageChip />
      <Button
        variant="primary"
        size="sm"
        onClick={() => {
          setScreen('new')
        }}
      >
        + Nova
      </Button>
    </header>
  )
}
