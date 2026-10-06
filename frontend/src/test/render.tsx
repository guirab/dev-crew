import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { createQueryClient } from '../api/queryClient'

/** `render` com TanStack Query (sem retry, pra erros aparecerem de primeira). `rerender` mantém o provider. */
export function renderWithClient(ui: ReactElement): RenderResult {
  const client = createQueryClient({ retry: false })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return render(ui, { wrapper })
}
