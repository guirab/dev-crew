import { useEffect, useState } from 'react'
import { Button } from '../ui/Button'

type CopyState = 'idle' | 'copied' | 'failed'

const LABEL: Record<Exclude<CopyState, 'idle'>, string> = {
  copied: 'Copiado',
  failed: 'Selecione e copie',
}

/** Copia `text` pra área de transferência; sem permissão/contexto seguro, orienta a copiar à mão. */
export function CopyButton({
  text,
  label = 'Copiar mensagem',
  variant = 'primary',
}: {
  text: string
  label?: string
  variant?: 'primary' | 'default'
}) {
  const [state, setState] = useState<CopyState>('idle')

  useEffect(() => {
    if (state === 'idle') return
    const timer = setTimeout(() => {
      setState('idle')
    }, 2500)
    return () => {
      clearTimeout(timer)
    }
  }, [state])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      setState('failed')
    }
  }

  return (
    <Button
      variant={variant}
      onClick={() => {
        void copy()
      }}
    >
      {state === 'idle' ? label : LABEL[state]}
    </Button>
  )
}
