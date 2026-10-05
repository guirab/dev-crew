import { useState } from 'react'
import type { InterviewQuestion } from '../contracts/generated'
import { useSendCommand } from '../api/commands'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { CommandErrorMessage } from './CommandErrorMessage'
import { Empty } from './Empty'
import type { BodyProps } from './types'
import b from './body.module.css'

const ACCEPTED_TEXT = '✓ Aceito a recomendação.'
/** Valor do rádio "outra resposta" (nenhuma opção real pode ser vazia). */
const OTHER = ''

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

/** Escolha de uma pergunta da rodada: uma opção (ou a recomendação) ou texto livre. */
interface Choice {
  picked: string
  other: string
}

const initialChoice = (q: InterviewQuestion): Choice => ({ picked: q.recommendation, other: '' })

/** `null` = aceitou a recomendação (contrato do `answer_interview`). */
function toAnswer(q: InterviewQuestion, c: Choice): string | null {
  if (c.picked !== OTHER) return c.picked === q.recommendation ? null : c.picked
  const text = c.other.trim()
  return text === '' || text === q.recommendation ? null : text
}

function QuestionField({
  question,
  choice,
  onChange,
}: {
  question: InterviewQuestion
  choice: Choice
  onChange: (next: Choice) => void
}) {
  const options = question.options.length > 0 ? question.options : [question.recommendation]
  const name = `q-${question.topic}`
  return (
    <fieldset className={b.question}>
      <legend>
        <span className={b.topic}>{question.topic}</span> {question.question}
      </legend>
      {question.rationale && <p className={b.rec}>{question.rationale}</p>}
      {options.map((option) => (
        <label key={option} className={b.option}>
          <input
            type="radio"
            name={name}
            value={option}
            checked={choice.picked === option}
            onChange={() => {
              onChange({ ...choice, picked: option })
            }}
          />
          <span>{option}</span>
          {option === question.recommendation && <span className={b.badge}>recomendada</span>}
        </label>
      ))}
      <label className={b.option}>
        <input
          type="radio"
          name={name}
          value={OTHER}
          checked={choice.picked === OTHER}
          onChange={() => {
            onChange({ ...choice, picked: OTHER })
          }}
        />
        <span>Outra resposta</span>
      </label>
      {choice.picked === OTHER && (
        <input
          aria-label={`Outra resposta: ${question.topic}`}
          placeholder="Escreva sua resposta…"
          value={choice.other}
          onChange={(e) => {
            onChange({ ...choice, other: e.target.value })
          }}
        />
      )}
    </fieldset>
  )
}

/** Rodada pendente: todas as perguntas da fronteira de uma vez, enviadas juntas. */
function RoundForm({ questions }: { questions: readonly InterviewQuestion[] }) {
  const [choices, setChoices] = useState<Choice[]>(() => questions.map(initialChoice))
  const send = useSendCommand()
  const incomplete = choices.some((c) => c.picked === OTHER && c.other.trim() === '')

  const submit = (answers: (string | null)[]) => {
    send.mutate({ type: 'answer_interview', answers })
  }

  return (
    <div className={b.sec}>
      <h4>
        {questions.length === 1 ? '1 pergunta' : `${questions.length} perguntas`} nesta rodada
      </h4>
      {questions.map((q, i) => (
        <QuestionField
          key={q.topic}
          question={q}
          choice={choices[i] ?? initialChoice(q)}
          onChange={(next) => {
            setChoices((current) => current.map((c, j) => (j === i ? next : c)))
          }}
        />
      ))}
      <div className={cx(b.row, b.end)}>
        <Button
          disabled={send.isPending}
          onClick={() => {
            submit(questions.map(() => null))
          }}
        >
          Aceitar todas as recomendações
        </Button>
        <Button
          variant="primary"
          disabled={send.isPending || incomplete}
          onClick={() => {
            submit(questions.map((q, i) => toAnswer(q, choices[i] ?? initialChoice(q))))
          }}
        >
          Enviar respostas
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </div>
  )
}

export function InterviewBody({ view, stage }: BodyProps) {
  const interview = view?.interview ?? null

  if (!interview) {
    return <Empty>Pergunta em rodadas, sempre com recomendação, até fechar a spec.</Empty>
  }

  const pending = interview.pending
  const awaitingAnswer = stage.status === 'waiting' && pending.length > 0

  return (
    <>
      {interview.turns.length > 0 && (
        <div className={cx(b.sec, b.chat)}>
          {interview.turns.map((turn, i) => (
            <div key={`${i}|${turn.question.question}`} className={b.chat}>
              <AgentMessage question={turn.question} />
              <div className={cx(b.msg, b.me)}>
                {turn.accepted_recommendation ? ACCEPTED_TEXT : turn.answer}
              </div>
            </div>
          ))}
        </div>
      )}
      {awaitingAnswer ? (
        // key: rodada nova = formulário novo, com as recomendações pré-selecionadas
        <RoundForm key={pending.map((q) => q.topic).join('|')} questions={pending} />
      ) : (
        pending.length > 0 && (
          <div className={cx(b.sec, b.chat)}>
            {pending.map((q) => (
              <AgentMessage key={q.topic} question={q} />
            ))}
          </div>
        )
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
