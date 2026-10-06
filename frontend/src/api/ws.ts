import type { WsMessage } from '../contracts/generated'
import { isWsMessage } from './guards'

/** Subconjunto de `WebSocket` que usamos (permite um fake nos testes sem `as`). */
export interface SocketLike {
  onopen: ((ev: Event) => void) | null
  onmessage: ((ev: MessageEvent) => void) | null
  onclose: ((ev: CloseEvent) => void) | null
  onerror: ((ev: Event) => void) | null
  close: () => void
}

export interface CrewSocketOptions {
  url: string
  onMessage: (msg: WsMessage) => void
  onStatus: (status: 'open' | 'closed') => void
  createSocket?: (url: string) => SocketLike
  baseDelayMs?: number
  maxDelayMs?: number
}

export function defaultSocketUrl(
  loc: Pick<Location, 'protocol' | 'host'> = window.location,
): string {
  return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/ws`
}

export function reconnectDelay(attempt: number, baseMs: number, maxMs: number): number {
  return Math.min(maxMs, baseMs * 2 ** attempt)
}

/**
 * Conexão `/ws` com reconexão exponencial (500ms → 10s). Retorna `dispose`.
 *
 * Sem heartbeat de aplicação: o contrato não define ping, e o servidor (uvicorn) já envia
 * ping/pong de protocolo, que o navegador responde sozinho. Conexão morta → `onclose` → reconecta.
 */
export function startCrewSocket(options: CrewSocketOptions): () => void {
  const {
    url,
    onMessage,
    onStatus,
    createSocket = (u) => new WebSocket(u),
    baseDelayMs = 500,
    maxDelayMs = 10_000,
  } = options

  let socket: SocketLike | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let attempt = 0
  let disposed = false

  const schedule = () => {
    timer = setTimeout(connect, reconnectDelay(attempt, baseDelayMs, maxDelayMs))
    attempt += 1
  }

  function connect() {
    timer = undefined
    const current = createSocket(url)
    socket = current
    current.onopen = () => {
      attempt = 0
      onStatus('open')
    }
    current.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return
      let parsed: unknown
      try {
        parsed = JSON.parse(ev.data)
      } catch {
        console.warn('[ws] mensagem não-JSON ignorada')
        return
      }
      if (isWsMessage(parsed)) onMessage(parsed)
      else console.warn('[ws] mensagem fora do contrato ignorada')
    }
    current.onclose = () => {
      if (disposed || socket !== current) return
      onStatus('closed')
      schedule()
    }
  }

  // Voltou a rede: não espera o backoff.
  const onOnline = () => {
    if (timer === undefined || disposed) return
    clearTimeout(timer)
    attempt = 0
    connect()
  }
  window.addEventListener('online', onOnline)

  connect()

  return () => {
    disposed = true
    if (timer !== undefined) clearTimeout(timer)
    window.removeEventListener('online', onOnline)
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onclose = null
      socket.close()
    }
  }
}
