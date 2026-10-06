import { useAccountUsage } from '../api/queries'
import styles from './Header.module.css'

function pct(value: number): string {
  return `${Math.round(value)}%`
}

/** Uso da assinatura no topo (D56). Some quando o dado não existe (sem login, sem cache do CLI). */
export function UsageChip() {
  const { data } = useAccountUsage()
  if (!data || (data.session_pct == null && data.weekly_pct == null)) return null
  const parts = [
    data.session_pct != null ? `sessão ${pct(data.session_pct)}` : null,
    data.weekly_pct != null ? `semana ${pct(data.weekly_pct)}` : null,
  ].filter(Boolean)
  const when = data.fetched_at ? new Date(data.fetched_at).toLocaleString('pt-BR') : 'desconhecido'
  return (
    <span
      className={styles.usage}
      title={`Uso da assinatura${data.plan ? ` (plano ${data.plan})` : ''}, medido pelo Claude Code em ${when}`}
    >
      {parts.join(' · ')}
    </span>
  )
}
