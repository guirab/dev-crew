import { useCrewStore } from '../store/crew'
import styles from './ReconnectBanner.module.css'

/** Faixa discreta no topo enquanto o WS está fora. Ao reconectar, o snapshot é re-hidratado. */
export function ReconnectBanner() {
  const connection = useCrewStore((s) => s.connection)
  if (connection !== 'closed') return null
  return (
    <div role="status" className={styles.banner}>
      reconectando…
    </div>
  )
}
