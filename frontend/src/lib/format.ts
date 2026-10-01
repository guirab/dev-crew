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
