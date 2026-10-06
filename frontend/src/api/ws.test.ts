import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { WsMessage } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import { defaultSocketUrl, reconnectDelay, startCrewSocket } from './ws'
import type { SocketLike } from './ws'

class FakeSocket implements SocketLike {
  onopen: SocketLike['onopen'] = null
  onmessage: SocketLike['onmessage'] = null
  onclose: SocketLike['onclose'] = null
  onerror: SocketLike['onerror'] = null
  closed = false

  constructor(readonly url: string) {}

  close(): void {
    this.closed = true
  }

  open(): void {
    this.onopen?.(new Event('open'))
  }

  receive(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  drop(): void {
    this.onclose?.(new CloseEvent('close'))
  }
}

describe('reconnectDelay', () => {
  it('é exponencial e limitado', () => {
    expect([0, 1, 2, 3].map((n) => reconnectDelay(n, 500, 10_000))).toEqual([500, 1000, 2000, 4000])
    expect(reconnectDelay(10, 500, 10_000)).toBe(10_000)
  })
})

describe('defaultSocketUrl', () => {
  it('usa ws/wss conforme o protocolo da página', () => {
    expect(defaultSocketUrl({ protocol: 'http:', host: 'localhost:5173' })).toBe(
      'ws://localhost:5173/ws',
    )
    expect(defaultSocketUrl({ protocol: 'https:', host: 'x.dev' })).toBe('wss://x.dev/ws')
  })
})

describe('startCrewSocket', () => {
  let sockets: FakeSocket[]
  let messages: WsMessage[]
  let statuses: ('open' | 'closed')[]

  const start = () =>
    startCrewSocket({
      url: 'ws://t/ws',
      onMessage: (m) => messages.push(m),
      onStatus: (s) => statuses.push(s),
      createSocket: (url) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
    })

  beforeEach(() => {
    vi.useFakeTimers()
    sockets = []
    messages = []
    statuses = []
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('conecta e reporta open', () => {
    start()
    expect(sockets).toHaveLength(1)
    sockets[0]?.open()
    expect(statuses).toEqual(['open'])
  })

  it('entrega view e progress válidos; ignora lixo', () => {
    start()
    const socket = sockets[0]
    socket?.receive(JSON.stringify({ type: 'view', data: fixture('planning') }))
    socket?.receive(JSON.stringify({ type: 'view', data: null }))
    socket?.receive('não é json')
    socket?.receive(JSON.stringify({ type: 'desconhecido' }))
    socket?.receive(new ArrayBuffer(2))
    expect(messages.map((m) => m.type)).toEqual(['view', 'view'])
  })

  it('reconecta com backoff exponencial e zera após abrir', () => {
    start()
    sockets[0]?.drop()
    expect(statuses).toEqual(['closed'])
    expect(sockets).toHaveLength(1)

    vi.advanceTimersByTime(499)
    expect(sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(2)

    sockets[1]?.drop() // 2ª falha seguida: espera 1000ms
    vi.advanceTimersByTime(999)
    expect(sockets).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(3)

    sockets[2]?.open() // conectou: backoff volta ao início
    sockets[2]?.drop()
    vi.advanceTimersByTime(500)
    expect(sockets).toHaveLength(4)
    expect(statuses).toEqual(['closed', 'closed', 'open', 'closed'])
  })

  it('dispose fecha o socket e cancela a reconexão pendente', () => {
    const dispose = start()
    sockets[0]?.drop()
    dispose()
    vi.advanceTimersByTime(60_000)
    expect(sockets).toHaveLength(1)

    const second = start()
    second()
    expect(sockets[1]?.closed).toBe(true)
  })

  it('evento "online" reconecta sem esperar o backoff', () => {
    start()
    sockets[0]?.drop()
    window.dispatchEvent(new Event('online'))
    expect(sockets).toHaveLength(2)
  })
})
