/** Junta nomes de classe ignorando valores vazios (CSS Modules indexados podem ser undefined). */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter((p): p is string => typeof p === 'string' && p.length > 0).join(' ')
}
