import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { resetCrewStore } from '../store/crew'
import { scrollIntoViewMock } from './dom'
import { server } from './server'

// O fetch do Node não aceita URL relativa (o app usa `/api/...`): resolve contra a origem do jsdom.
const nodeFetch = globalThis.fetch
vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) =>
  typeof input === 'string' && input.startsWith('/')
    ? nodeFetch(new URL(input, window.location.origin), init)
    : nodeFetch(input, init),
)

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetCrewStore()
})

afterAll(() => {
  server.close()
})

// jsdom não implementa estas APIs de layout; os componentes dependem delas.
class ResizeObserverStub implements ResizeObserver {
  observe(): void {
    // jsdom não tem layout
  }
  unobserve(): void {
    // jsdom não tem layout
  }
  disconnect(): void {
    // jsdom não tem layout
  }
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)

Element.prototype.scrollIntoView = scrollIntoViewMock

if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  })
}
