import { cx } from '../lib/cx'
import styles from './Backdrop.module.css'

/** Manchas desfocadas atrás de tudo: dão ao vidro algo pra desfocar. Só animam com tarefa rodando. */
export function Backdrop({ animated }: { animated: boolean }) {
  return (
    <div className={cx(styles.backdrop, animated && styles.animated)} aria-hidden="true">
      <span className={styles.a} />
      <span className={styles.b} />
      <span className={styles.c} />
    </div>
  )
}
