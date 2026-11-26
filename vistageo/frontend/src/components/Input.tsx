import type { InputHTMLAttributes } from 'react'

type Props = InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string; error?: string; trailing?: React.ReactNode }

export function Input({ label, hint, error, trailing, className = '', ...rest }: Props) {
  return (
    <label className="block">
      {label && <span className="mb-1.5 block text-sm font-semibold text-text-primary">{label}</span>}
      <div className="relative">
        <input
          aria-invalid={error ? true : undefined}
          className={`min-h-12 w-full rounded-lg border bg-surface px-3.5 py-2.5 text-base text-text-primary outline-none placeholder:text-slate-400 focus:border-action focus:ring-2 focus:ring-action/15 sm:text-sm ${error ? 'border-danger-strong focus:border-danger-strong focus:ring-danger/10' : 'border-border'} ${className}`}
          {...rest}
        />
        {trailing && <div className="absolute inset-y-0 right-3 flex items-center">{trailing}</div>}
      </div>
      {hint && !error && <span className="mt-1.5 block text-xs text-text-secondary">{hint}</span>}
      {error && <span className="mt-1.5 block text-xs font-semibold text-danger-strong">{error}</span>}
    </label>
  )
}
