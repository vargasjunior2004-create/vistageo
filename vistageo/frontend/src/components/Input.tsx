import type { InputHTMLAttributes } from 'react'

type Props = InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string; error?: string; trailing?: React.ReactNode }

export function Input({ label, hint, error, trailing, className = '', ...rest }: Props) {
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>}
      <div className="relative">
        <input
          className={`min-h-12 w-full rounded-xl border bg-white px-3.5 py-2.5 text-base text-slate-900 outline-none placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10 sm:text-sm ${error ? 'border-rose-500 focus:border-rose-500 focus:ring-rose-500/10' : 'border-slate-300'} ${className}`}
          {...rest}
        />
        {trailing && <div className="absolute inset-y-0 right-3 flex items-center">{trailing}</div>}
      </div>
      {hint && !error && <span className="mt-1.5 block text-xs text-slate-500">{hint}</span>}
      {error && <span className="mt-1.5 block text-xs font-medium text-rose-600">{error}</span>}
    </label>
  )
}
