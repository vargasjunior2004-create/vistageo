import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import type { Contract } from '../types/api'

export function ContractsPage() {
  const pageSize = 100
  const [items, setItems] = useState<Contract[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [kardex, setKardex] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const deliberateLoad = useRef(false)

  const load = useCallback(async (signal?: AbortSignal, activity = false) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: String(pageSize + 1), offset: String(offset) })
      if (filter) params.set('kardex', filter)
      const results = await apiRequest<Contract[]>(`/contratos?${params}`, { signal, activity })
      if (signal?.aborted) return
      setItems(results.slice(0, pageSize))
      setHasNext(results.length > pageSize)
    } catch (err) {
      if (!signal?.aborted) setError((err as Error).message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [filter, offset])

  useEffect(() => {
    const controller = new AbortController()
    const activity = deliberateLoad.current
    deliberateLoad.current = false
    void load(controller.signal, activity)
    return () => controller.abort()
  }, [load])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await apiRequest('/contratos', { method: 'POST', body: { kardex } })
      setKardex('')
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">Contratos</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <form onSubmit={(e) => { e.preventDefault(); if (filter === search && offset === 0) void load(undefined, true); else { deliberateLoad.current = true; setOffset(0); setFilter(search) } }} className="flex flex-wrap items-end gap-2">
        <div className="flex-1"><Input label="Buscar kardex exacto" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <Button type="submit">Buscar</Button>
      </form>
      <form onSubmit={create} className="flex flex-wrap items-end gap-2 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
        <div className="flex-1">
          <Input label="Kardex" value={kardex} onChange={(e) => setKardex(e.target.value)} />
        </div>
        <Button type="submit">Crear</Button>
      </form>
      {loading ? (
        <p className="text-slate-500">Cargando...</p>
      ) : (
        <div className="overflow-x-auto rounded-3xl bg-white shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr><th className="px-4 py-3">Kardex</th></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.kardex} className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium">{c.kardex}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
