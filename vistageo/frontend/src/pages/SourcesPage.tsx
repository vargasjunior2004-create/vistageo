import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import type { HistoricalSource } from '../types/api'

export function SourcesPage() {
  const pageSize = 100
  const [items, setItems] = useState<HistoricalSource[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({ carpeta: '', estado: '', kardex: '', tipo: '' })
  const [applied, setApplied] = useState(filters)
  const [offset, setOffset] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const deliberateLoad = useRef(false)

  const load = useCallback(async (signal?: AbortSignal, activity = false) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: String(pageSize + 1), offset: String(offset) })
      if (applied.carpeta) params.set('carpeta', applied.carpeta)
      if (applied.estado) params.set('estado', applied.estado)
      if (applied.kardex) params.set('kardex', applied.kardex)
      if (applied.tipo) params.set('tipo', applied.tipo)
      const results = await apiRequest<HistoricalSource[]>(`/procedencia?${params}`, { signal, activity })
      if (signal?.aborted) return
      setItems(results.slice(0, pageSize))
      setHasNext(results.length > pageSize)
    } catch (err) {
      if (!signal?.aborted) setError((err as Error).message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [applied, offset])

  useEffect(() => {
    const controller = new AbortController()
    const activity = deliberateLoad.current
    deliberateLoad.current = false
    void load(controller.signal, activity)
    return () => controller.abort()
  }, [load])

  const confirm = async (source: HistoricalSource, kardex: string) => {
    setError('')
    try {
      await apiRequest(`/procedencia/${source.id}/contrato`, { method: 'PUT', body: { kardex } })
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const unconfirm = async (source: HistoricalSource) => {
    setError('')
    try {
      await apiRequest(`/procedencia/${source.id}/contrato`, { method: 'DELETE' })
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">Procedencia histórica</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="grid gap-2 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100 sm:grid-cols-4">
        <Input label="Carpeta" value={filters.carpeta} onChange={(e) => setFilters({ ...filters, carpeta: e.target.value })} />
        <Input label="Estado" value={filters.estado} onChange={(e) => setFilters({ ...filters, estado: e.target.value })} />
        <Input label="Kardex" value={filters.kardex} onChange={(e) => setFilters({ ...filters, kardex: e.target.value })} />
        <Input label="Tipo" value={filters.tipo} onChange={(e) => setFilters({ ...filters, tipo: e.target.value })} />
      </div>
      <Button onClick={() => { deliberateLoad.current = true; setOffset(0); setApplied({ ...filters }) }}>Filtrar</Button>

      {loading ? (
        <p className="text-slate-500">Cargando...</p>
      ) : (
        <div className="space-y-2">
          {items.map((s) => (
            <div key={s.id} className="rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
              <p className="font-medium text-slate-900">#{s.id} · {s.tipo}</p>
              <p className="text-sm text-slate-600 break-all">{s.ruta_original}</p>
              <p className="text-xs text-slate-400">
                SHA: {s.sha256 ?? '—'} · Estado: {s.estado_revision} · Kardex: {s.kardex ?? '—'}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    const k = prompt('Kardex a confirmar', s.kardex ?? '')
                    if (k) confirm(s, k)
                  }}
                >
                  Confirmar contrato
                </Button>
                <Button variant="ghost" onClick={() => unconfirm(s)}>Retirar</Button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button variant="secondary" disabled={offset === 0 || loading} onClick={() => { deliberateLoad.current = true; setOffset(Math.max(0, offset - pageSize)) }}>Anterior</Button>
        <span className="text-sm text-slate-600">Página {Math.floor(offset / pageSize) + 1}</span>
        <Button variant="secondary" disabled={!hasNext || loading} onClick={() => { deliberateLoad.current = true; setOffset(offset + pageSize) }}>Siguiente</Button>
      </div>
    </div>
  )
}
