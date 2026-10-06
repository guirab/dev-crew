import type { Estimate } from '../contracts/generated'
import { formatTokens, formatUsd } from '../lib/format'
import styles from './EstimateBox.module.css'
import b from './body.module.css'

function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(value < 10 ? 1 : 0).replace('.', ',')}%`
}

/**
 * Quanto o plano deve custar (D56). `share` (0..1) reduz o total pros épicos marcados; o detalhe de
 * cálculo e as fontes ficam em `basis`, que vem pronto do orquestrador.
 */
export function EstimateBox({ estimate, share = 1 }: { estimate: Estimate; share?: number }) {
  const scale = (value: number | null) => (value == null ? null : value * share)
  const now = estimate.usage_now
  const partial = share < 0.999

  return (
    <div className={b.sec}>
      <h4>Estimativa{partial ? ' dos épicos marcados' : ''}</h4>
      <dl className={styles.grid}>
        <div>
          <dt>tokens</dt>
          <dd>~{formatTokens(Math.round(estimate.tokens * share))}</dd>
        </div>
        <div>
          <dt>equivalente API</dt>
          <dd>~{formatUsd(estimate.usd * share)}</dd>
        </div>
        <div>
          <dt>da sessão (5 h)</dt>
          <dd>{pct(scale(estimate.session_pct))}</dd>
        </div>
        <div>
          <dt>da semana</dt>
          <dd>{pct(scale(estimate.weekly_pct))}</dd>
        </div>
      </dl>
      {now && (now.session_pct != null || now.weekly_pct != null) && (
        <p className={styles.note}>
          Uso agora{now.plan ? ` (plano ${now.plan})` : ''}: sessão {pct(now.session_pct)} · semana{' '}
          {pct(now.weekly_pct)}
        </p>
      )}
      {estimate.sessions_needed != null && estimate.sessions_needed > 1 && !partial && (
        <p className={styles.note}>
          Deve passar por ~{estimate.sessions_needed} sessões de 5 h: o trabalho para no limite e
          você retoma.
        </p>
      )}
      <p className={styles.basis}>{estimate.basis}</p>
    </div>
  )
}
