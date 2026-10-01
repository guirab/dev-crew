import { cx } from '../lib/cx'
import b from './body.module.css'

/** Texto de estado vazio dentro de um corpo expandido. */
export function Empty({ children }: { children: string }) {
  return <div className={cx(b.sec, b.muted)}>{children}</div>
}
