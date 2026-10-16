import { useSendCommand } from '../api/commands'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import type { UsageLimit } from '../contracts/generated'
import { formatResetTime } from '../lib/format'
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert'
import { Button } from '../ui/Button'
import styles from './LimitBanner.module.css'

/**
 * A assinatura bateu o limite de uso (D50): o trabalho parou e só volta quando o usuário mandar.
 * O dev-crew não espera nem tenta de novo sozinho.
 */
export function LimitBanner({ limit }: { limit: UsageLimit }) {
  const send = useSendCommand()
  const reset = limit.resets_at ? formatResetTime(limit.resets_at) : ''

  return (
    <Alert className={styles.banner} role="alert" aria-label="Limite de uso atingido">
      <AlertTitle role="heading" aria-level={3} className={styles.title}>
        {limit.message}
      </AlertTitle>
      <AlertDescription className={styles.text}>
        {reset
          ? `O trabalho parou. A cota volta ${reset}; depois disso, retome daqui.`
          : 'O trabalho parou. Retome quando a cota da assinatura voltar.'}
      </AlertDescription>
      <div className={styles.row}>
        <Button
          variant="primary"
          disabled={send.isPending}
          onClick={() => {
            send.mutate({ type: 'resume_after_limit' })
          }}
        >
          Retomar
        </Button>
        <Button
          disabled={send.isPending}
          onClick={() => {
            if (window.confirm('Cancelar a tarefa atual? As alterações locais ficam no repo.')) {
              send.mutate({ type: 'cancel_task' })
            }
          }}
        >
          Cancelar tarefa
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </Alert>
  )
}
