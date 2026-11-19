import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { LocationPhoto } from '../components/LocationPhoto'
import type { Location, LocationRevision } from '../types/api'

export function LocationsPage() {
  const pageSize = 100
  const [locations, setLocations] = useState<Location[]>([])
  const [selected, setSelected] = useState<Location | null>(null)
  const [revisions, setRevisions] = useState<LocationRevision[]>([])
  const [revisionVersion, setRevisionVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [kardex, setKardex] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const deliberateLoad = useRef(false)
  const [url, setUrl] = useState('')
  const [lat, setLat] = useState('')
  const [lng, setLng] = useState('')

  const load = useCallback(async (signal?: AbortSignal, activity = false) => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: String(pageSize + 1), offset: String(offset) })
      if (filter) params.set('kardex', filter)
      const results = await apiRequest<Location[]>(`/ubicaciones?${params}`, { signal, activity })
      if (signal?.aborted) return
      setLocations(results.slice(0, pageSize))
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

  const createLocation = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await apiRequest('/ubicaciones', { method: 'POST', body: { kardex } })
      setKardex('')
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setRevisions([])
    setError('')
    apiRequest<LocationRevision[]>(`/ubicaciones/${selected.id}/revisiones`, { activity: true, signal: controller.signal })
      .then(setRevisions)
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [selected, revisionVersion])

  const addRevision = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selected) return
    setError('')
    try {
      const body: Record<string, unknown> = {}
      if (url) body.url_gps = url
      if (lat) body.latitud = lat
      if (lng) body.longitud = lng
      await apiRequest(`/ubicaciones/${selected.id}/revisiones`, { method: 'POST', body })
      setUrl('')
      setLat('')
      setLng('')
      setRevisionVersion((version) => version + 1)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-slate-900">Ubicaciones</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <form onSubmit={(e) => { e.preventDefault(); setSelected(null); if (filter === search && offset === 0) void load(undefined, true); else { deliberateLoad.current = true; setOffset(0); setFilter(search) } }} className="flex flex-wrap items-end gap-2">
        <div className="flex-1"><Input label="Buscar kardex exacto" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <Button type="submit">Buscar</Button>
      </form>
      <form onSubmit={createLocation} className="flex flex-wrap items-end gap-2 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
        <div className="flex-1">
          <Input label="Kardex" value={kardex} onChange={(e) => setKardex(e.target.value)} />
        </div>
        <Button type="submit">Crear ubicación</Button>
      </form>

      {loading ? (
        <p className="text-slate-500">Cargando...</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {locations.map((loc) => (
            <button
              key={loc.id}
              onClick={() => setSelected(loc)}
              className={`rounded-2xl p-4 text-left shadow transition ${selected?.id === loc.id ? 'bg-blue-50 ring-2 ring-blue-600' : 'bg-white hover:bg-slate-50'}`}
            >
              <p className="font-semibold text-slate-900">#{loc.id}</p>
              <p className="text-sm text-slate-600">{loc.kardex}</p>
              <p className="text-xs text-slate-400">Revisión actual: {loc.revision_actual_id ?? '—'}</p>
            </button>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button variant="secondary" disabled={offset === 0 || loading} onClick={() => { deliberateLoad.current = true; setOffset(Math.max(0, offset - pageSize)); setSelected(null) }}>Anterior</Button>
        <span className="text-sm text-slate-600">Página {Math.floor(offset / pageSize) + 1}</span>
        <Button variant="secondary" disabled={!hasNext || loading} onClick={() => { deliberateLoad.current = true; setOffset(offset + pageSize); setSelected(null) }}>Siguiente</Button>
      </div>

      {selected && (
        <div className="space-y-3 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <h2 className="font-semibold">Revisiones de {selected.kardex}</h2>
          <LocationPhoto key={selected.id} locationId={selected.id} />
          <form onSubmit={addRevision} className="grid gap-2 sm:grid-cols-3">
            <Input label="URL GPS" value={url} onChange={(e) => setUrl(e.target.value)} />
            <Input label="Latitud" value={lat} onChange={(e) => setLat(e.target.value)} />
            <Input label="Longitud" value={lng} onChange={(e) => setLng(e.target.value)} />
            <div className="sm:col-span-3">
              <Button type="submit">Agregar revisión</Button>
            </div>
          </form>
          <ul className="space-y-2">
            {revisions.map((r) => (
              <li key={r.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <p className="font-medium">#{r.id} {r.cerrada ? '(cerrada)' : ''}</p>
                <p className="text-slate-600">{r.url_gps ?? 'Sin URL'}</p>
                <p className="text-xs text-slate-400">
                  {r.latitud ?? '—'}, {r.longitud ?? '—'} · {new Date(r.registrado_en).toLocaleString()}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
