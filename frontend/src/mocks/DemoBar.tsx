import { useEffect, useReducer } from 'react'
import { getMockControls } from './controls'
import styles from './DemoBar.module.css'

const SPEEDS = [1, 2, 4, 8] as const

/** Barra de demo (só no modo mock): velocidade, forçar escalada e queda do WS. */
export default function DemoBar() {
  const controls = getMockControls()
  const [, refresh] = useReducer((n: number) => n + 1, 0)

  // O cenário zera "forçar escalada" depois que o usuário age; re-renderiza a cada mensagem.
  useEffect(() => controls?.backend.subscribe(refresh), [controls])

  if (!controls) return null
  const { scenario, fixtureName, disconnectAll } = controls

  return (
    <div className={styles.bar} role="group" aria-label="Controles do modo demo">
      <span>{fixtureName ? `fixture: ${fixtureName}` : 'demo'}</span>
      {scenario && (
        <>
          <select
            aria-label="Velocidade"
            value={scenario.speed}
            onChange={(e) => {
              scenario.setSpeed(Number(e.target.value))
              refresh()
            }}
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}x
              </option>
            ))}
          </select>
          <label>
            <input
              type="checkbox"
              checked={scenario.forceEscalate}
              onChange={(e) => {
                scenario.setForceEscalate(e.target.checked)
                refresh()
              }}
            />
            forçar escalada
          </label>
        </>
      )}
      <button type="button" className={styles.drop} onClick={disconnectAll}>
        derrubar ws
      </button>
    </div>
  )
}
