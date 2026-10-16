import { vi } from 'vitest'
import type { NodeKey } from '../flow/timeline'

/** Mock de `scrollIntoView` (jsdom não implementa). Instalado no setup global. */
export const scrollIntoViewMock = vi.fn()

/** Um nó da linha do tempo da tarefa (`data-node`), com o tom em `data-tone`. */
export function node(key: NodeKey): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-node="${key}"]`)
  if (!el) throw new Error(`nó ${key} não encontrado`)
  return el
}

/** O cabeçalho clicável do nó (nós futuros não têm). */
export function nodeButton(key: NodeKey): HTMLElement {
  const el = node(key).querySelector<HTMLElement>(':scope > button')
  if (!el) throw new Error(`nó ${key} sem cabeçalho clicável`)
  return el
}

export const isNodeOpen = (key: NodeKey): boolean =>
  node(key).querySelector(':scope > [role="region"]') !== null

/** O card aberto do nó. */
export function nodeBody(key: NodeKey): HTMLElement {
  const el = node(key).querySelector<HTMLElement>(':scope > [role="region"]')
  if (!el) throw new Error(`nó ${key} fechado`)
  return el
}
