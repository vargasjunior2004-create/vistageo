import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'accent' }

const styles: Record<string, string> = {
  primary: 'bg-blue-700 text-white hover:bg-blue-800 shadow-sm',
  secondary: 'bg-white text-[#102c50] hover:bg-blue-50 border border-slate-300 shadow-sm',
  danger: 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm shadow-rose-600/20',
  ghost: 'bg-transparent text-blue-700 hover:bg-blue-50',
  accent: 'bg-blue-700 text-white hover:bg-blue-800 shadow-sm',
}

export function Button({ variant = 'primary', className = '', children, ...rest }: Props) {
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
