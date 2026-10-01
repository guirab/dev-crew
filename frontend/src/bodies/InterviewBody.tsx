import { useRef, useState } from 'react'
import type { InterviewQuestion } from '../contracts/generated'
import { useSendCommand } from '../api/commands'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { CommandErrorMessage } from './CommandErrorMessage'
import { Empty } from './Empty'
import type { BodyProps } from './types'
import b from './body.module.css'

const ACCEPTED_TEXT = '✓ Aceito a recomendação.'

function AgentMessage({ question }: { question: InterviewQuestion }) {
  return (
    <div className={b.msg}>
      {question.question}
      <div className={b.rec}>
        <b>Recomendo:</b> {question.recommendation}
      </div>
      {question.rationale && <div className={b.rec}>{question.rationale}</div>}
    </div>
  )
}

export function InterviewBody({ view, stage }: BodyProps) {
  const [answer, setAnswer] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const send = useSendCommand()
  const interview = view?.interview ?? null

  if (!interview) {
    return (
      <Empty>
        {view?.source === 'azure'
          ? 'Pulado — tarefa veio do Azure DevOps.'
          : 'Entra só em tarefa manual: uma pergunta por vez, sempre com recomendação, até fechar a spec.'}
      </Empty>
    )
  }

  const awaitingAnswer = stage.status === 'waiting' && interview.pending !== null
  const text = answer.trim()

  const submit = (reply: string | null) => {
    send.mutate(
      { type: 'answer_interview', text: reply },
      {
        onSuccess: () => {
          // limpa só o que foi enviado: se o usuário já digitou outra coisa, preserva
          setAnswer((current) => (reply !== null && current.trim() === reply ? '' : current))
          inputRef.current?.focus()
        },
      },
    )
  }

  return (
    <>
      <div className={cx(b.sec, b.chat)}>
        {interview.turns.map((turn, i) => (
          <div key={`${i}|${turn.question.question}`} className={b.chat}>
            <AgentMessage question={turn.question} />
            <div className={cx(b.msg, b.me)}>
              {turn.accepted_recommendation ? ACCEPTED_TEXT : turn.answer}
            </div>
          </div>
        ))}
        {interview.pending && <AgentMessage question={interview.pending} />}
      </div>
      {awaitingAnswer && (
        <div className={b.sec}>
          <div className={b.row}>
            <input
              ref={inputRef}
              aria-label="Responder diferente"
              placeholder="Responder diferente…"
              style={{ flex: 1, minWidth: 180, width: 'auto' }}
              value={answer}
              onChange={(e) => {
                setAnswer(e.target.value)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && text !== '' && !send.isPending) submit(text)
              }}
            />
            <Button
              disabled={send.isPending || text === ''}
              onClick={() => {
                submit(text)
              }}
            >
              Enviar
            </Button>
            <Button
              variant="primary"
              disabled={send.isPending}
              onClick={() => {
                submit(null)
              }}
            >
              Aceitar recomendação
            </Button>
          </div>
          <CommandErrorMessage error={send.error} />
        </div>
      )}
      {interview.decisions.length > 0 && (
        <div className={b.sec}>
          <h4>Spec</h4>
          <ul>
            {interview.decisions.map((decision, i) => (
              <li key={`${i}|${decision}`}>{decision}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}
