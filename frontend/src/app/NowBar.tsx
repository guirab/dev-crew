import { useEffect, useState } from 'react'
import { useSendCommand } from '../api/commands'
import { Progress } from '../components/ui/progress'
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip'
import type { TaskView } from '../contracts/generated'
import { epicProgress } from '../flow/lanes'
import { cx } from '../lib/cx'
import { formatDuration, formatTokens, formatUsd } from '../lib/format'
import { isRunning, useCrewStore } from '../store/crew'
import { Button } from '../ui/Button'
import { nowStatus } from './nowStatus'
import styles from './NowBar.module.css'

/** Relógio que anda de 1 em 1 s enquanto `ticking`; parado devolve a hora do último tique. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!ticking) return
    const id = setInterval(() => {
      setNow(Date.now())
    }, 1000)
    return () => {
      clearInterval(id)
    }
  }, [ticking])
  return now
}

/** Faixa "Agora": estado da tarefa, tempo, tokens, custo x estimativa e o único CTA quando é a vez do usuário. */
export function NowBar({ view }: { view: TaskView }) {
  const progress = useCrewStore((s) => s.progress)
  const focusOn = useCrewStore((s) => s.focusOn)
  const setOpenEpic = useCrewStore((s) => s.setOpenEpic)
  const cancel = useSendCommand()
  const now = useNow(view.ended_at === null)
  const status = nowStatus(view, progress)
  const cta = status.cta

  const end = view.ended_at ? Date.parse(view.ended_at) : now
  const elapsed = (end - Date.parse(view.started_at)) / 1000
  const estimate = view.estimate?.usd ?? 0
  const epics = epicProgress(view.epics)

  return (
    <section className={cx(styles.bar, styles[status.tone])} aria-label="Agora">
      <span className={styles.pulse} aria-hidden="true" />
      <div className={styles.what}>
        <b>{status.headline}</b>
        {status.detail && <span className={styles.detail}>{status.detail}</span>}
      </div>
      {epics.total > 0 && (
        <div className={styles.progress}>
          <span className={styles.progressLabel}>
            épicos <b>{`${String(epics.done)}/${String(epics.total)} prontos`}</b>
          </span>
          <Progress
            value={(epics.done / epics.total) * 100}
            aria-label="Épicos prontos"
            className={styles.progressBar}
          />
        </div>
      )}
      <dl className={styles.metrics}>
        <div>
          <dt>tempo</dt>
          <dd>{formatDuration(Number.isNaN(elapsed) ? 0 : elapsed)}</dd>
        </div>
        <div>
          <dt>tokens</dt>
          <dd>{formatTokens(view.tokens)}</dd>
        </div>
        <div>
          <dt>{estimate > 0 ? 'custo / estimativa' : 'custo'}</dt>
          <dd>
            {estimate > 0 ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  {/* foco por teclado é o que abre o tooltip */}
                  {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
                  <span tabIndex={0}>
                    {formatUsd(view.cost_usd)}
                    <span className={styles.dim}> / ~{formatUsd(estimate)}</span>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {`${String(Math.round((view.cost_usd / estimate) * 100))}% da estimativa já gasto`}
                </TooltipContent>
              </Tooltip>
            ) : (
              formatUsd(view.cost_usd)
            )}
          </dd>
          {estimate > 0 && (
            <span className={styles.budget} aria-hidden="true">
              <span style={{ width: `${String(Math.min(view.cost_usd / estimate, 1) * 100)}%` }} />
            </span>
          )}
        </div>
      </dl>
      <div className={styles.actions}>
        {cancel.error && (
          <span role="alert" className={styles.cancelError}>
            {cancel.error.message}
          </span>
        )}
        {isRunning(view) && (
          <Button
            variant="link"
            disabled={cancel.isPending}
            onClick={() => {
              if (window.confirm('Cancelar a tarefa atual? As alterações locais ficam no repo.')) {
                cancel.mutate({ type: 'cancel_task' })
              }
            }}
          >
            cancelar tarefa
          </Button>
        )}
        {cta && (
          <Button
            variant="primary"
            className={cx(status.tone === 'attention' && styles.ctaWait)}
            onClick={() => {
              focusOn(cta.target)
              if (cta.epic) setOpenEpic(cta.epic)
            }}
          >
            {cta.epic ? cta.label : `${cta.label} ↓`}
          </Button>
        )}
      </div>
    </section>
  )
}
