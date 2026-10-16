import type { ComponentProps } from 'react'
import { Input as ShadcnInput } from '../components/ui/input'
import { cn } from '../lib/utils'

/** Input do shadcn; o visual glass (poço, borda, foco verde) vem do global.css. */
export function Input({ className, ...rest }: ComponentProps<typeof ShadcnInput>) {
  return <ShadcnInput className={cn('h-auto', className)} {...rest} />
}
