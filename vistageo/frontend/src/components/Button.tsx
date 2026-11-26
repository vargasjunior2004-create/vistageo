import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'accent' }

const styles: Record<string, string> = {
  primary: 'bg-action-strong text-white hover:bg-primary',
  secondary: 'border border-border bg-surface text-primary hover:bg-background',
  danger: 'bg-danger text-white hover:bg-danger-strong',
  ghost: 'bg-transparent text-action-strong hover:bg-blue-50',
  accent: 'bg-action-strong text-white hover:bg-primary',
}

export function Button({ variant = 'primary', className = '', children, ...rest }: Props) {
  return (
    <button
      className={`inline-flex min-h-12 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
