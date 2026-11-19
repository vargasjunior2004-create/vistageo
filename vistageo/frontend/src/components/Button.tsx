import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'accent' }

const styles: Record<string, string> = {
  primary: 'bg-teal-600 text-white hover:bg-teal-700 shadow-sm shadow-teal-600/20',
  secondary: 'bg-white text-slate-700 hover:bg-slate-50 border border-slate-200 shadow-sm',
  danger: 'bg-rose-600 text-white hover:bg-rose-700 shadow-sm shadow-rose-600/20',
  ghost: 'bg-transparent text-teal-700 hover:bg-teal-50',
  accent: 'bg-amber-500 text-white hover:bg-amber-600 shadow-sm shadow-amber-500/20',
}

export function Button({ variant = 'primary', className = '', children, ...rest }: Props) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
