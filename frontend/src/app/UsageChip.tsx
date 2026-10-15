import { useAccountUsage } from '../api/queries'
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip'
import { cx } from '../lib/cx'
import styles from './Header.module.css'

/** Mais velho que isso, o número já não é o consumo de agora: o chip avisa (D61 mede a cada minuto). */
export const STALE_AFTER_MS = 10 * 60_000

function pct(value: number): string {
  return `${Math.round(value)}%`
}

function age(ms: number): string {
  const minutes = Math.floor(ms / 60_000)
  if (minutes < 60) return `${String(minutes)} min`
  const hours = Math.floor(minutes / 60)
  return hours < 48 ? `${String(hours)} h` : `${String(Math.floor(hours / 24))} d`
}

/** Uso da assinatura no topo (D56). Some quando o dado não existe (sem login, sem cache do CLI). */
export function UsageChip() {
  const { data, dataUpdatedAt } = useAccountUsage()
  if (!data || (data.session_pct == null && data.weekly_pct == null)) return null
  const parts = [
    data.session_pct != null ? `sessão ${pct(data.session_pct)}` : null,
    data.weekly_pct != null ? `semana ${pct(data.weekly_pct)}` : null,
  ].filter(Boolean)
  const fetched = data.fetched_at ? Date.parse(data.fetched_at) : null
  // idade no momento da última resposta (a consulta roda a cada minuto)
  const elapsed = fetched == null ? null : dataUpdatedAt - fetched
  const stale = elapsed == null || elapsed > STALE_AFTER_MS
  const when = fetched == null ? 'desconhecido' : new Date(fetched).toLocaleString('pt-BR')
  const title = stale
    ? `Uso desatualizado: o Claude Code não mede desde ${when}. Confira o login (claude auth login).`
    : `Uso da assinatura${data.plan ? ` (plano ${data.plan})` : ''}, medido pelo Claude Code em ${when}`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* foco por teclado é o que abre o tooltip */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
        <span className={cx(styles.usage, stale && styles.stale)} tabIndex={0}>
          {parts.join(' · ')}
          {stale && ` · desatualizado${elapsed == null ? '' : ` há ${age(elapsed)}`}`}
        </span>
      </TooltipTrigger>
      <TooltipContent>{title}</TooltipContent>
    </Tooltip>
  )
}
