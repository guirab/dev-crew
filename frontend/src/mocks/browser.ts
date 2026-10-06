import { setupWorker } from 'msw/browser'
import type { MockBackend } from './backend'
import { setMockControls } from './controls'
import { FixtureBackend, loadFixture } from './fixtureBackend'
import { createRestHandlers, createWsHandler } from './handlers'
import { ScenarioBackend } from './scenario'

/**
 * Liga o MSW (REST + WS). Query params:
 *  - `?fixture=<nome>`  snapshot estático de contracts/fixtures/view.<nome>.json
 *  - `?escalate=1`      Tester falha sempre → escalada
 *  - `?speed=<n>`       multiplicador de velocidade do cenário (default 1)
 */
export async function startMocking(): Promise<void> {
  const params = new URLSearchParams(window.location.search)
  const fixtureName = params.get('fixture')

  let backend: MockBackend
  let scenario: ScenarioBackend | null = null
  if (fixtureName) {
    backend = new FixtureBackend(await loadFixture(fixtureName), fixtureName)
  } else {
    scenario = new ScenarioBackend({
      speed: Number(params.get('speed')) || 1,
      forceEscalate: params.get('escalate') === '1',
    })
    backend = scenario
  }

  const { handler, disconnectAll } = createWsHandler(backend)
  const worker = setupWorker(...createRestHandlers(backend, { latencyMs: 150 }), handler)
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true })

  setMockControls({ backend, scenario, fixtureName, disconnectAll })
}
