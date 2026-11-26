import { useCallback, useEffect, useRef, useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { LocationPhoto } from '../components/LocationPhoto'
import { Skeleton, SkeletonCard } from '../components/Skeleton'
import { UpdateLocation } from '../components/UpdateLocation'
import type { Location, LocationRevision } from '../types/api'

export function LocationsPage() {
  const { user, hasPermission } = useAuth()
  const pageSize = 100
  const [locations, setLocations] = useState<Location[]>([])
  const [selected, setSelected] = useState<Location | null>(null)
  const [revisions, setRevisions] = useState<LocationRevision[]>([])
  const [revisionsLoading, setRevisionsLoading] = useState(false)
  const [revisionVersion, setRevisionVersion] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [kardex, setKardex] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const deliberateLoad = useRef(false)
  const [photoVersion, setPhotoVersion] = useState<string | null>(null)
  const [photoRevision, setPhotoRevision] = useState(0)

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
      if (!signal?.aborted) {
        setLoading(false)
        setLoaded(true)
      }
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
    setRevisionsLoading(true)
    setError('')
    apiRequest<LocationRevision[]>(`/ubicaciones/${selected.id}/revisiones`, { activity: true, signal: controller.signal })
      .then(setRevisions)
      .catch((err: Error) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setRevisionsLoading(false) })
    return () => controller.abort()
  }, [selected, revisionVersion])

  const refreshSelected = async (id: number) => {
    setPhotoVersion(null)
    setPhotoRevision((value) => value + 1)
    try {
      const current = await apiRequest<Location>(`/ubicaciones/${id}`)
      setSelected((previous) => previous?.id === id ? current : previous)
      setRevisionVersion((version) => version + 1)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo actualizar la ficha.')
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="page-title">Ubicaciones</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <form onSubmit={(e) => { e.preventDefault(); setSelected(null); if (filter === search && offset === 0) void load(undefined, true); else { deliberateLoad.current = true; setOffset(0); setFilter(search) } }} className="flex flex-wrap items-end gap-2">
        <div className="flex-1"><Input label="Buscar kardex exacto" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <Button type="submit">Buscar</Button>
      </form>
      <form onSubmit={createLocation} className="surface-panel flex flex-wrap items-end gap-3 p-5">
        <div className="flex-1">
          <Input label="Kardex" value={kardex} onChange={(e) => setKardex(e.target.value)} />
        </div>
        <Button type="submit">Crear ubicación</Button>
      </form>

      {loading && !loaded ? <div role="status" aria-label="Cargando ubicaciones" className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => <SkeletonCard key={index} rows={2} />)}
      </div> : (
        <div className="grid gap-3 sm:grid-cols-2">
          {locations.length === 0 && !error ? <p className="col-span-full rounded-xl bg-white p-5 text-slate-600">No se encontraron ubicaciones.</p> : locations.map((loc) => (
            <button
              key={loc.id}
              onClick={() => { setPhotoVersion(null); setSelected(loc) }}
              className={`rounded-xl border p-4 text-left transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 ${selected?.id === loc.id ? 'border-[#2f6ecb] bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
            >
              <p className="font-semibold text-slate-900">#{loc.id}</p>
              <p className="text-sm text-slate-600">{loc.kardex}</p>
              <p className="text-xs text-slate-400">Última revisión histórica: {loc.revision_actual_id ?? '—'}</p>
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
        <div className="surface-panel space-y-3 p-5">
          <h2 className="font-semibold">Ubicación de {selected.kardex}</h2>
          <LocationPhoto key={`${selected.id}-${photoRevision}`} locationId={selected.id} onVersion={setPhotoVersion} />
          <p className="text-sm text-slate-600">Coordenadas vigentes: {selected.latitud ?? '—'}, {selected.longitud ?? '—'} {selected.url_gps ?? ''}</p>
          <p className="text-sm text-slate-600">Origen vigente: {selected.metodo_coordenadas === 'GPS_DISPOSITIVO' ? 'GPS del dispositivo' : selected.metodo_coordenadas === 'ENLACE_COMPARTIDO' ? 'Enlace compartido' : 'Desconocido'}</p>
          <p className="text-sm text-slate-600">Precisión estimada: {selected.precision_metros === null ? 'No disponible' : `${selected.precision_metros} m`}</p>
          {user && <UpdateLocation key={selected.id} userId={user.id} location={selected} photoVersion={photoVersion}
            canPhoto={hasPermission('ubicaciones.fotografia.editar')} canGps={hasPermission('ubicaciones.gps.editar')}
            onUpdated={() => void refreshSelected(selected.id)} />}
          <h3 className="font-semibold">Revisiones históricas</h3>
          {revisionsLoading ? <div role="status" aria-label="Cargando revisiones históricas"><Skeleton className="h-16 w-full rounded-xl" /></div> : revisions.length === 0 && !error
            ? <p className="text-sm text-slate-600">No hay revisiones históricas disponibles.</p>
            : <ul className="space-y-2">{revisions.map((r) => (
              <li key={r.id} className="rounded-lg border border-slate-200 p-3 text-sm">
                <p className="font-medium">#{r.id} {r.cerrada ? '(cerrada)' : ''}</p>
                <p>Origen: {r.metodo_coordenadas === 'GPS_DISPOSITIVO' ? 'GPS del dispositivo' : r.metodo_coordenadas === 'ENLACE_COMPARTIDO' ? 'Enlace compartido' : 'Desconocido'}</p>
                <p>Precisión estimada: {r.precision_metros === null ? 'No disponible' : `${r.precision_metros} m`}</p>
                <p className="text-slate-600">{r.url_gps ?? 'Sin URL'}</p>
                <p className="text-xs text-slate-400">
                  {r.latitud ?? '—'}, {r.longitud ?? '—'} · {new Date(r.registrado_en).toLocaleString()}
                </p>
              </li>
            ))}</ul>}
        </div>
      )}
    </div>
  )
}
