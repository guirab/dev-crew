import { http, HttpResponse } from 'msw'
import type { Command, CommandReply } from '../contracts/generated'
import { server } from './server'

/**
 * Intercepta `POST /api/commands` e acumula os corpos recebidos.
 * `reply` pode ser trocado por teste (ex.: 409) e `gate` segura a resposta (estado de loading).
 */
export function captureCommands(reply: { status?: number; body?: CommandReply } = {}): {
  received: unknown[]
  release: () => void
  hold: () => void
} {
  const received: unknown[] = []
  let gate: Promise<void> | null = null
  let open: () => void = () => undefined

  server.use(
    http.post('*/api/commands', async ({ request }) => {
      received.push(await request.json())
      if (gate) await gate
      return HttpResponse.json(reply.body ?? { ok: true, error: null, view: null }, {
        status: reply.status ?? 200,
      })
    }),
  )

  return {
    received,
    hold: () => {
      gate = new Promise<void>((resolve) => {
        open = resolve
      })
    },
    release: () => {
      open()
      gate = null
    },
  }
}

export type { Command }
