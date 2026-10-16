import type { ComponentProps } from 'react'
import { Label as ShadcnLabel } from '../components/ui/label'
import { cn } from '../lib/utils'

export function Label({ className, ...rest }: ComponentProps<typeof ShadcnLabel>) {
  return (
    <ShadcnLabel
      className={cn(
        'block font-[family-name:var(--mono)] text-[11.5px] leading-normal font-normal text-[color:var(--muted)]',
        className,
      )}
      {...rest}
    />
  )
}
