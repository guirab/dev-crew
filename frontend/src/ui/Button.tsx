import type { ButtonHTMLAttributes } from 'react'
import { cx } from '../lib/cx'
import styles from './Button.module.css'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
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
    <button
      type={type}
      className={cx(
        variant === 'link' ? styles.link : styles.btn,
        variant === 'primary' && styles.primary,
        size === 'sm' && styles.sm,
        className,
      )}
      {...rest}
    />
  )
}
