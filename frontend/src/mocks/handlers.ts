import { delay, http, HttpResponse, ws } from 'msw'
import type { Command } from '../contracts/generated'
import type { MockBackend } from './backend'

const COMMAND_TYPES: readonly string[] = [
  'start_task',
  'answer_interview',
  'approve_plan',
  'adjust_plan',
  'escalation',
  'cancel_task',
  'resume_after_limit',
  'run_epics',
  'finish_task',
  'create_project',
  'add_repo',
]

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Validação mínima de `Command` pro mock (o gateway real valida com Pydantic). */
export function isCommand(v: unknown): v is Command {
  if (!isRecord(v) || typeof v.type !== 'string' || !COMMAND_TYPES.includes(v.type)) return false
  switch (v.type) {
    case 'start_task':
      return typeof v.repo === 'string' && typeof v.title === 'string'
    case 'adjust_plan':
      return typeof v.text === 'string'
    case 'add_repo':
      return (
        typeof v.name === 'string' && typeof v.path === 'string' && typeof v.test_cmd === 'string'
      )
    case 'escalation':
      return v.action === 'instruct' || v.action === 'more_attempts' || v.action === 'replan'
    default:
      return true
  }
}

interface RestOptions {
  /** Latência artificial das listas, pra enxergar os estados de loading no navegador. */
  latencyMs?: number
}

/** REST do gateway (`/api/*`). O prefixo `*` casa qualquer origem (browser e jsdom). */
export function createRestHandlers(backend: MockBackend, { latencyMs = 0 }: RestOptions = {}) {
  const lag = async () => {
    if (latencyMs > 0) await delay(latencyMs)
  }
  return [
    http.get('*/api/repos', async () => {
      await lag()
      return HttpResponse.json(backend.repos)
    }),
    http.get('*/api/folders', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? undefined
      const listing = backend.folders.list(path)
      return listing
        ? HttpResponse.json(listing)
        : HttpResponse.json({ detail: `a pasta não existe: ${path ?? ''}` }, { status: 404 })
    }),
    http.get('*/api/folders/probe', ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? ''
      const probe = backend.folders.probe(path)
      return probe
        ? HttpResponse.json(probe)
        : HttpResponse.json({ detail: `a pasta não existe: ${path}` }, { status: 404 })
    }),
    http.get('*/api/task', () => HttpResponse.json(backend.getView())),
    http.get('*/api/tasks', async () => {
      await lag()
      return HttpResponse.json(backend.getTasks())
    }),
    http.get('*/api/usage', () =>
      HttpResponse.json({
        plan: 'pro',
        session_pct: 12,
        session_resets_at: null,
        weekly_pct: 14,
        weekly_resets_at: null,
        fetched_at: null,
      }),
    ),
    http.post('*/api/commands', async ({ request }) => {
      const body: unknown = await request.json().catch(() => null)
      if (!isCommand(body)) {
        return HttpResponse.json(
          { ok: false, error: 'Comando inválido.', view: null },
          { status: 422 },
        )
      }
      const { status, reply } = backend.handle(body)
      return HttpResponse.json(reply, { status })
    }),
  ]
}

/** `WS /ws`: manda o snapshot atual ao conectar e repassa tudo que o backend emitir. */
export function createWsHandler(backend: MockBackend) {
  const link = ws.link('*/ws')
  const handler = link.addEventListener('connection', ({ client }) => {
    client.send(JSON.stringify({ type: 'view', data: backend.getView() }))
    const unsubscribe = backend.subscribe((msg) => {
      client.send(JSON.stringify(msg))
    })
    client.addEventListener('close', unsubscribe)
  })
  return {
    handler,
    /** Derruba todos os clientes (simula queda do gateway → banner "reconectando…"). */
    disconnectAll: () => {
      for (const client of link.clients) client.close()
    },
  }
}
