import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { Button } from '../ui/Button'
import { CommandErrorMessage } from './CommandErrorMessage'
import b from './body.module.css'

/**
 * Escalada: o loop estourou e a decisão é do usuário. A UI só envia o comando escolhido;
 * quem sabe quantas tentativas, qual transição e o que acontece depois é o orquestrador.
 */
export function EscalationPanel({ reason }: { reason: string }) {
  const [instruction, setInstruction] = useState('')
  const send = useSendCommand()
  const text = instruction.trim()

  return (
    <div className={b.sec}>
      <h4>Loop estourou — o que fazer?</h4>
      <p className={b.muted} style={{ margin: '0 0 10px' }}>
        {reason}
      </p>
      <div style={{ marginBottom: 12 }}>
        <textarea
          aria-label="Instrução pro Developer"
          placeholder="Instrução pro Developer, ex.: usar fake timers no teste de concorrência"
          value={instruction}
          onChange={(e) => {
            setInstruction(e.target.value)
          }}
        />
      </div>
      <div className={b.row}>
        <Button
          variant="primary"
          disabled={send.isPending || text === ''}
          onClick={() => {
            send.mutate({ type: 'escalation', action: 'instruct', text })
          }}
        >
          Enviar instrução
        </Button>
        <Button
          disabled={send.isPending}
          onClick={() => {
            send.mutate({ type: 'escalation', action: 'more_attempts' })
          }}
        >
          +2 tentativas
        </Button>
        <Button
          disabled={send.isPending}
          onClick={() => {
            send.mutate({ type: 'escalation', action: 'replan' })
          }}
        >
          Voltar pro Planner
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
    </div>
  )
}
