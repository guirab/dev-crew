import './styles/tokens.css'
import './styles/global.css'
import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { createQueryClient } from './api/queryClient'
import { App } from './app/App'
import { CrewConnection } from './app/CrewConnection'

// Só em dev: `import.meta.env.DEV` é constante em build, então o chunk não vai pra produção.
const Gallery = import.meta.env.DEV ? lazy(() => import('./dev/Gallery')) : null
const showGallery = Gallery !== null && window.location.pathname === '/dev/gallery'

async function bootstrap(): Promise<void> {
  const root = document.getElementById('root')
  if (!root) throw new Error('#root not found')

  // `npm run dev:mock`: MSW intercepta REST + WS. Em produção este branch é eliminado.
  if (import.meta.env.MODE === 'mock') {
    try {
      const { startMocking } = await import('./mocks/browser')
      await startMocking()
    } catch (error) {
      // ex.: ?fixture=<nome inexistente>. Mostra na tela em vez de uma página em branco.
      const message = document.createElement('pre')
      message.style.cssText = 'color:#ff5d5d;padding:24px;font:13px monospace;white-space:pre-wrap'
      message.textContent = error instanceof Error ? error.message : String(error)
      root.replaceChildren(message)
      throw error
    }
  }

  const queryClient = createQueryClient()
  createRoot(root).render(
    <StrictMode>
      {Gallery && showGallery ? (
        <Suspense fallback={null}>
          <Gallery />
        </Suspense>
      ) : (
        <QueryClientProvider client={queryClient}>
          <CrewConnection />
          <App />
        </QueryClientProvider>
      )}
    </StrictMode>,
  )
}

void bootstrap()
