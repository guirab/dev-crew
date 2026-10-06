import type { MockBackend } from './backend'
import type { ScenarioBackend } from './scenario'

/** Pontes entre o worker MSW (browser.ts) e a DemoBar. Só existe no modo mock. */
export interface MockControls {
  backend: MockBackend
  /** `null` no modo `?fixture=`. */
  scenario: ScenarioBackend | null
  fixtureName: string | null
  disconnectAll: () => void
}

let current: MockControls | null = null

export function setMockControls(controls: MockControls): void {
  current = controls
}

export function getMockControls(): MockControls | null {
  return current
}
