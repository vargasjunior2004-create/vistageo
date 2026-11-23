import type { ButtonHTMLAttributes } from 'react'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'accent' }

const styles: Record<string, string> = {
  primary: 'bg-[#2f6ecb] text-white hover:bg-[#275ca8]',
  secondary: 'border border-slate-300 bg-white text-[#102c50] hover:bg-slate-50',
  danger: 'bg-rose-700 text-white hover:bg-rose-800',
  ghost: 'bg-transparent text-[#2f6ecb] hover:bg-slate-100',
  accent: 'bg-[#2f6ecb] text-white hover:bg-[#275ca8]',
}

export function Button({ variant = 'primary', className = '', children, ...rest }: Props) {
  return (
    <button
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2f6ecb] disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}
