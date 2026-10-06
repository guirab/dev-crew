/** "HH:MM:SS" no fuso local; vazio se o ISO for inválido. */
export function formatClock(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toTimeString().slice(0, 8)
}

/** 45 → "45s", 125 → "2m 05s". */
export function formatDuration(totalSeconds: number): string {
  const total = Math.max(0, Math.round(totalSeconds))
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`
}

/** Cobertura como fração (0.87 → "87%"), como nas fixtures do contrato. */
export function formatPercent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`
}

/** Quando a cota volta, no fuso local: "às 15:00" hoje, "seg. às 15:00" em outro dia; vazio se inválido. */
export function formatResetTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const time = date.toTimeString().slice(0, 5)
  if (date.toDateString() === now.toDateString()) return `às ${time}`
  const day = date.toLocaleDateString('pt-BR', { weekday: 'short' })
  return `${day} às ${time}`
}

/** 1234 → "1,2 mil", 2_500_000 → "2,5 mi". */
export function formatTokens(value: number): string {
  if (value < 1000) return String(value)
  if (value < 1_000_000) return `${(value / 1000).toFixed(1).replace('.', ',')} mil`
  return `${(value / 1_000_000).toFixed(1).replace('.', ',')} mi`
}
