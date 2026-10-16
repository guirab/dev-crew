import type { ComponentProps } from 'react'
import { cva } from 'class-variance-authority'
import { Button as ShadcnButton } from '../components/ui/button'
import { cn } from '../lib/utils'

const glassButton = cva(
  'h-auto cursor-pointer transition-[transform,background-color] duration-200',
  {
    variants: {
      variant: {
        default:
          'rounded-full border border-white/20 bg-white/10 px-[18px] py-[9px] font-semibold text-inherit shadow-[inset_0_1px_0_rgb(255_255_255/32%)] [transition:transform_0.4s_var(--spring),background_0.2s] hover:bg-white/20 enabled:hover:-translate-y-px enabled:hover:scale-[1.03] disabled:opacity-35 disabled:shadow-none',
        primary:
          'rounded-full border border-white/55 bg-[linear-gradient(180deg,#6dffb0,var(--green))] px-[18px] py-[9px] font-[650] text-[#03150c] shadow-[inset_0_1px_0_rgb(255_255_255/80%),0_10px_28px_color-mix(in_srgb,var(--green)_40%,transparent)] [transition:transform_0.4s_var(--spring),background_0.2s] hover:bg-[linear-gradient(180deg,var(--green-hi),var(--green))] enabled:hover:-translate-y-px enabled:hover:scale-[1.03] disabled:opacity-35 disabled:shadow-none',
        link: 'rounded-none border-none bg-transparent px-1.5 py-px font-normal text-[var(--muted)] hover:bg-transparent hover:text-[var(--err)] hover:no-underline',
      },
      size: {
        md: '',
        sm: '',
      },
    },
    compoundVariants: [
      { variant: ['default', 'primary'], size: 'sm', class: 'px-[13px] py-[5px] text-[13px]' },
    ],
  },
)

interface ButtonProps extends Omit<ComponentProps<typeof ShadcnButton>, 'variant' | 'size'> {
  variant?: 'default' | 'primary' | 'link'
  size?: 'md' | 'sm'
}

export function Button({
  variant = 'default',
  size = 'md',
  type = 'button',
  className,
  ...rest
}: ButtonProps) {
  return (
    <ShadcnButton type={type} className={cn(glassButton({ variant, size }), className)} {...rest} />
  )
}
