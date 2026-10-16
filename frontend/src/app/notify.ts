import { useEffect, useRef, useState } from 'react'
import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { describe, FAVICON_HREF } from './tabStatus'
import type { FaviconKind } from './tabStatus'

/** Estados que merecem aviso fora da janela: precisa de você, concluída, erro/limite. */
const NOTIFY: readonly FaviconKind[] = ['attention', 'done', 'error']

const supported = () => typeof Notification !== 'undefined'

/**
 * Aviso do sistema quando a tarefa passa a esperar o usuário, termina ou dá erro, só com a janela em
 * segundo plano e permissão dada. O 1º snapshot de uma tarefa (abrir/recarregar) não avisa.
 */
export function useAttentionNotification(view: TaskView | null): void {
  const setScreen = useCrewStore((s) => s.setScreen)
  const kind = view ? describe(view).favicon : null
  const last = useRef<{ task: string; kind: FaviconKind } | null>(null)

  useEffect(() => {
    if (!view || !kind) return
    const previous = last.current
    last.current = { task: view.task_id, kind }
    if (previous?.task !== view.task_id || previous.kind === kind) return
    if (!NOTIFY.includes(kind) || !document.hidden) return
    if (!supported() || Notification.permission !== 'granted') return
    const notification = new Notification(
      `${view.task_id} · ${describe(view).state.replace(/^● /, '')}`,
      {
        body: view.escalation?.reason ?? view.limit?.message ?? view.title,
        tag: view.task_id,
        icon: FAVICON_HREF[kind],
      },
    )
    notification.onclick = () => {
      window.focus()
      setScreen('task')
      notification.close()
    }
  }, [view, kind, setScreen])
}

/** Permissão de aviso do navegador; `null` quando não há suporte. */
export function useNotificationPermission(): [NotificationPermission | null, () => void] {
  const [permission, setPermission] = useState(() => (supported() ? Notification.permission : null))
  const ask = () => {
    void Notification.requestPermission().then(setPermission)
  }
  return [permission, ask]
}
