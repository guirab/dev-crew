import { useId } from 'react'
import type { ReactNode } from 'react'
import { cx } from '../lib/cx'
import styles from './Field.module.css'

interface FieldProps {
  label: string
  inline?: boolean
  /** Recebe o id a ser aplicado no controle, ligando `<label htmlFor>`. */
  children: (id: string) => ReactNode
}

export function Field({ label, inline = false, children }: FieldProps) {
  const id = useId()
  return (
    <div className={cx(styles.field, inline && styles.inline)}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      {children(id)}
    </div>
  )
}
