import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useCrewStore } from '../store/crew'
import { currentTaskQuery } from './queries'
import { defaultSocketUrl, startCrewSocket } from './ws'

/**
 * Liga o WS ao store: `view` substitui o snapshot, `progress` alimenta a linha ao vivo.
 * A cada (re)conexão, `GET /api/task` re-hidrata (o WS pode ter perdido snapshots).
 */
export function useCrewConnection(url: string = defaultSocketUrl()): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    const rehydrate = async () => {
      const sinceVersion = useCrewStore.getState().viewVersion
      try {
        const view = await queryClient.query(currentTaskQuery)
        useCrewStore.getState().hydrate(view, sinceVersion)
      } catch {
        // REST fora: o próximo snapshot do WS resolve; não trava a UI esperando.
        useCrewStore.getState().markHydrated()
      }
    }

    return startCrewSocket({
      url,
      onMessage: (msg) => {
        const store = useCrewStore.getState()
        if (msg.type === 'view') store.applyView(msg.data)
        else store.applyProgress(msg)
      },
      onStatus: (status) => {
        useCrewStore.getState().setConnection(status)
        if (status === 'open') void rehydrate()
      },
    })
  }, [queryClient, url])
}
