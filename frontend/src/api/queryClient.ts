import { QueryClient } from '@tanstack/react-query'

export function createQueryClient(options: { retry?: number | false } = {}): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: options.retry ?? 1, refetchOnWindowFocus: false },
      // Comandos nunca são reenviados sozinhos (não são idempotentes).
      mutations: { retry: false },
    },
  })
}
