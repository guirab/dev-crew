import type { CommandError as CommandErrorType } from '../api/client'
import b from './body.module.css'

/** Erro inline de um comando (409/422/rede). */
export function CommandErrorMessage({ error }: { error: CommandErrorType | null }) {
  if (!error) return null
  return (
    <p role="alert" className={b.error}>
      {error.message}
    </p>
  )
}
