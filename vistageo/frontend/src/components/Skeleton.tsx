import type { CSSProperties } from 'react'

type SkeletonProps = {
  className?: string
  style?: CSSProperties
}

export function Skeleton({ className = '', style }: SkeletonProps) {
  return <span aria-hidden="true" className={`skeleton ${className}`} style={style} />
}

export function SkeletonText({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden="true" className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          className={`h-3.5 rounded-md ${index === lines - 1 ? 'w-2/3' : 'w-full'}`}
        />
      ))}
    </div>
  )
}

export function SkeletonAvatar({ className = 'h-10 w-10' }: SkeletonProps) {
  return <Skeleton className={`shrink-0 rounded-full ${className}`} />
}

export function SkeletonImage({ className = '', aspectRatio = '4 / 3' }: SkeletonProps & { aspectRatio?: string }) {
  return <Skeleton className={`rounded-xl ${className}`} style={{ aspectRatio }} />
}

export function SkeletonCard({ rows = 3, image = false, className = '' }: SkeletonProps & { rows?: number; image?: boolean }) {
  return (
    <div aria-hidden="true" className={`surface-panel space-y-4 p-5 ${className}`}>
      {image && <SkeletonImage className="w-full" />}
      <Skeleton className="h-4 w-2/5 rounded-md" />
      <SkeletonText lines={rows} />
    </div>
  )
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div aria-hidden="true" className="surface-panel overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            {Array.from({ length: columns }, (_, column) => (
              <th key={column} className="px-4 py-3 text-left">
                <Skeleton className="h-3.5 w-3/4 rounded-md" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, row) => (
            <tr key={row} className="border-t border-slate-100">
              {Array.from({ length: columns }, (_, column) => (
                <td key={column} className="px-4 py-3">
                  <Skeleton className={`h-3.5 rounded-md ${column === 0 ? 'w-3/5' : 'w-4/5'}`} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SkeletonDashboard() {
  return (
    <div role="status" aria-label="Cargando aplicación" className="min-h-screen bg-slate-50 lg:flex">
      <span className="sr-only">Cargando aplicación...</span>
      <aside aria-hidden="true" className="hidden w-64 shrink-0 flex-col gap-8 bg-[#102c50] p-5 lg:flex">
        <Skeleton className="skeleton-on-brand h-10 w-40 rounded-lg" />
        <div className="space-y-3">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="skeleton-on-brand h-9 w-full rounded-md" />
          ))}
        </div>
        <div className="mt-auto flex items-center gap-3">
          <SkeletonAvatar className="skeleton-on-brand h-9 w-9" />
          <Skeleton className="skeleton-on-brand h-4 w-28 rounded-md" />
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <header aria-hidden="true" className="flex min-h-16 items-center border-b border-slate-200 bg-white px-5 sm:px-8">
          <Skeleton className="h-4 w-36 rounded-md" />
        </header>
        <main className="mx-auto max-w-6xl space-y-8 px-4 py-7 sm:px-7 lg:px-8">
          <section aria-hidden="true" className="space-y-4 border-b border-slate-200 pb-8">
            <Skeleton className="h-4 w-28 rounded-md" />
            <Skeleton className="h-9 w-3/4 max-w-lg rounded-md" />
            <Skeleton className="h-4 w-full max-w-xl rounded-md" />
            <Skeleton className="h-4 w-36 rounded-md" />
          </section>
          {[0, 1].map((group) => (
            <section key={group} aria-hidden="true" className="space-y-4">
              <Skeleton className="h-5 w-36 rounded-md" />
              <Skeleton className="h-4 w-64 max-w-full rounded-md" />
              <div className="grid gap-3 sm:grid-cols-2">
                {[0, 1].map((card) => <SkeletonCard key={card} rows={2} className="min-h-28" />)}
              </div>
            </section>
          ))}
        </main>
      </div>
    </div>
  )
}
