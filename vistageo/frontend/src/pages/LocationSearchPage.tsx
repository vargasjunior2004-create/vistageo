import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { LocationPhoto } from '../components/LocationPhoto'
import { UpdateLocation } from '../components/UpdateLocation'
import { googleMapsLink } from '../services/maps'
import type { Location, LocationRevision, LocationUpdateAudit } from '../types/api'

const PAGE_SIZE = 25
const DEBOUNCE_MS = 350

function mapsLink(location: Location | null): string | null {
  if (!location) return null
  if (location.latitud !== null && location.longitud !== null) {
    return googleMapsLink(location.latitud, location.longitud)
  }
  if (!location.url_gps) return null
  try {
    const url = new URL(location.url_gps)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

function Highlight({ value, query }: { value: string; query: string }) {
  const lowered = value.toLowerCase()
  const needle = query.toLowerCase()
  const index = lowered.indexOf(needle)
  if (index < 0 || lowered.length !== value.length || needle.length !== query.length) return <>{value}</>
  return <>{value.slice(0, index)}<mark className="rounded bg-amber-100 text-inherit">{value.slice(index, index + query.length)}</mark>{value.slice(index + query.length)}</>
}

function VisibleWhitespace({ value }: { value: string }) {
  if (!/\s/.test(value)) return null
  return <span className="mt-1 block break-all text-xs text-slate-600">Espacios visibles (␠): {JSON.stringify(value).replaceAll(' ', '␠')}</span>
}

function LazyPhoto({ locationId }: { locationId: number }) {
  const target = useRef<HTMLSpanElement>(null)
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    const node = target.current
    if (!node) return
    if (typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setVisible(true)
        observer.disconnect()
      }
    }, { rootMargin: '200px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return <span ref={target} className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-slate-100">{visible && <LocationPhoto locationId={locationId} thumbnail />}</span>
}

export function LocationSearchPage() {
  const { hasPermission, user } = useAuth()
  const allowed = hasPermission('ubicaciones.consultar')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const [retry, setRetry] = useState(0)
  const [results, setResults] = useState<Location[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Location | null>(null)
  const [history, setHistory] = useState<LocationUpdateAudit[]>([])
  const [revisionResult, setRevisionResult] = useState<{ id: number; revision: LocationRevision | null; error: string } | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [historyMore, setHistoryMore] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [photoVersion, setPhotoVersion] = useState<string | null>(null)
  const [photoRevision, setPhotoRevision] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  const detail = useRef<HTMLElement>(null)
  const selectedId = selected?.id

  useEffect(() => {
    if (!allowed || query.length === 0) return
    const controller = new AbortController()
    controllerRef.current = controller
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({
        kardex_contiene: query, limit: String(PAGE_SIZE + 1), offset: String(page * PAGE_SIZE),
      })
      apiRequest<Location[]>(`/ubicaciones?${params}`, { signal: controller.signal, activity: page === 0 })
        .then((items) => {
          if (controller.signal.aborted) return
          setResults((previous) => page === 0 ? items.slice(0, PAGE_SIZE) : [...previous, ...items.slice(0, PAGE_SIZE)])
          setHasMore(items.length > PAGE_SIZE)
        })
        .catch((err: unknown) => {
          if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'No se pudo buscar el kardex.')
        })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, page === 0 ? DEBOUNCE_MS : 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [allowed, query, page, retry])

  useEffect(() => {
    const node = sentinel.current
    if (!node || !hasMore || loading || error || selected || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        observer.disconnect()
        setLoading(true)
        setPage((previous) => previous + 1)
      }
    }, { rootMargin: '300px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore, loading, error, selected, results])

  useEffect(() => {
    if (selectedId === undefined) return
    detail.current?.focus()
  }, [selectedId])

  useEffect(() => {
    if (selectedId === undefined) return
    const controller = new AbortController()
    apiRequest<LocationUpdateAudit[]>(`/ubicaciones/${selectedId}/actualizaciones?limit=26`, { signal: controller.signal, activity: true })
      .then((items) => {
        if (controller.signal.aborted) return
        setHistory(items.slice(0, 25))
        setHistoryMore(items.length > 25)
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setHistoryError(err instanceof Error ? err.message : 'No se pudo cargar el historial.')
      })
      .finally(() => { if (!controller.signal.aborted) setHistoryLoading(false) })
    return () => controller.abort()
  }, [selectedId, photoRevision])

  useEffect(() => {
    if (selectedId === undefined || !selected?.revision_actual_id) return
    const controller = new AbortController()
    apiRequest<LocationRevision[]>(`/ubicaciones/${selectedId}/revisiones?revision_id=${selected.revision_actual_id}`, { signal: controller.signal })
      .then((items) => { if (!controller.signal.aborted) setRevisionResult({ id: selectedId, revision: items[0] ?? null, error: '' }) })
      .catch((err: unknown) => { if (!controller.signal.aborted) setRevisionResult({ id: selectedId, revision: null, error: err instanceof Error ? err.message : 'No se pudo consultar la revisión.' }) })
    return () => controller.abort()
  }, [selectedId, selected?.revision_actual_id])

  const refreshLocation = async (locationId: number) => {
    setPhotoVersion(null)
    setHistoryLoading(true)
    setHistoryError('')
    setPhotoRevision((value) => value + 1)
    try {
      const current = await apiRequest<Location>(`/ubicaciones/${locationId}`)
      setSelected((previous) => previous?.id === locationId ? { ...current, registro_pendiente: previous.registro_pendiente } : previous)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'No se pudo actualizar la ficha.')
    }
  }

  const moreHistory = async () => {
    if (!selected) return
    setHistoryLoading(true)
    setHistoryError('')
    try {
      const rows = await apiRequest<LocationUpdateAudit[]>(`/ubicaciones/${selected.id}/actualizaciones?limit=26&offset=${history.length}`)
      setHistory((previous) => [...previous, ...rows.slice(0, 25)])
      setHistoryMore(rows.length > 25)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'No se pudo cargar el historial.')
    } finally { setHistoryLoading(false) }
  }

  if (!allowed) return <p>No tienes permiso para esta función.</p>
  const link = mapsLink(selected)
  const registrationRevision = revisionResult && revisionResult.id === selectedId ? revisionResult.revision : null
  const revisionError = revisionResult && revisionResult.id === selectedId ? revisionResult.error : ''

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link to="/" className="text-sm font-semibold text-blue-700">← Volver al panel</Link>
      <header className="rounded-3xl bg-[#102c50] p-6 text-white">
        <p className="text-sm text-blue-200">VISTA GEO · Ubicación oficial</p>
        <h1 className="mt-1 text-2xl font-bold">Consultar ubicación</h1>
      </header>
      <div className="rounded-3xl bg-white p-5 shadow-sm">
        <Input label="Buscar por kardex" value={query} autoComplete="off" hint="Ingresa el kardex exacto para encontrar una ubicación específica o escribe una parte para ver las coincidencias." onChange={(event) => {
          const value = event.target.value
          controllerRef.current?.abort()
          setQuery(value)
          setPage(0)
          setResults([])
          setHasMore(false)
          setLoading(value.length > 0)
          setError('')
          setSelected(null)
        }} />
        <p className="mt-2 text-xs text-slate-600">Las mayúsculas y los espacios pueden distinguir kardex diferentes.</p>
      </div>
      {selected ? (
        <section ref={detail} tabIndex={-1} className="space-y-4 rounded-3xl bg-white p-5 shadow-sm outline-none">
          <button type="button" className="text-sm font-semibold text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2" onClick={() => setSelected(null)}>← Volver a coincidencias</button>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Kardex · Ubicación #{selected.id}</p>
            <h2 className="mt-1 break-all whitespace-pre-wrap text-xl font-bold text-slate-900">{selected.kardex}</h2>
            <VisibleWhitespace value={selected.kardex} />
            <p className="mt-2 text-sm text-slate-600">Registrado por: {selected.creado_por_nombre ?? 'Desconocido'}</p>
            <p className="text-sm text-slate-600">Fecha de registro: {selected.creado_en ? new Date(selected.creado_en).toLocaleString() : 'Desconocida'}</p>
          </div>
          {selected.registro_pendiente && <p role="status" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Este registro está pendiente o requiere revisión. Contacta a un administrador si no tienes el borrador original.</p>}
          <LocationPhoto key={`${selected.id}-${photoRevision}`} locationId={selected.id} onVersion={setPhotoVersion} />
          {user && (hasPermission('ubicaciones.fotografia.editar') || hasPermission('ubicaciones.gps.editar')) && <UpdateLocation
            key={selected.id}
            userId={user.id}
            location={selected}
            photoVersion={photoVersion}
            canPhoto={hasPermission('ubicaciones.fotografia.editar')}
            canGps={hasPermission('ubicaciones.gps.editar')}
            onUpdated={() => void refreshLocation(selected.id)}
          />}
          {selected.latitud !== null ? <p className="text-sm text-slate-600">{selected.latitud}, {selected.longitud}</p> : <p className="text-sm text-slate-600">No hay coordenadas vigentes.</p>}
          <p className="text-sm text-slate-600">Origen de las coordenadas vigentes: {selected.metodo_coordenadas === 'GPS_DISPOSITIVO' ? 'GPS del dispositivo' : selected.metodo_coordenadas === 'ENLACE_COMPARTIDO' ? 'Enlace compartido' : 'Desconocido'}</p>
          {selected.url_gps && <p className="break-all text-sm text-slate-600">URL GPS: {selected.url_gps}</p>}
          {link && <><p className="break-all text-sm text-slate-600">Enlace: {link}</p><a className="inline-block rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white" href={link} target="_blank" rel="noopener noreferrer">Abrir ubicación</a></>}
          <section className="space-y-2 border-t border-slate-100 pt-4">
            <h3 className="font-semibold">Historial de actualizaciones</h3>
            {revisionError && <p role="alert" className="text-sm text-red-700">{revisionError}</p>}
            {registrationRevision && <div className="rounded-xl bg-slate-50 p-3 text-sm">
              <p className="font-semibold">Revisión histórica vinculada</p>
              <p>Origen: {registrationRevision.metodo_coordenadas === 'GPS_DISPOSITIVO' ? 'GPS del dispositivo' : registrationRevision.metodo_coordenadas === 'ENLACE_COMPARTIDO' ? 'Enlace compartido' : 'Desconocido'}</p>
              <p>{registrationRevision.latitud ?? '—'}, {registrationRevision.longitud ?? '—'} · {new Date(registrationRevision.registrado_en).toLocaleString()}</p>
              {registrationRevision.url_gps && <p className="break-all">Enlace original: {registrationRevision.url_gps}</p>}
            </div>}
            {historyError && <p role="alert" className="text-sm text-red-700">{historyError}</p>}
            {historyLoading && <p role="status" className="text-sm text-slate-500">Cargando historial...</p>}
            {!historyLoading && history.length === 0 && !historyError && <p className="text-sm text-slate-600">Aún no hay actualizaciones registradas.</p>}
            <ul className="space-y-2">{history.map((item) => <li key={item.id} className="rounded-xl bg-slate-50 p-3 text-sm">
              <p className="font-semibold">{item.motivo}</p>
              <p>{item.usuario} · {new Date(item.fecha).toLocaleString()}</p>
              <p>{[item.fachada && 'Fachada', item.gps && 'GPS'].filter(Boolean).join(' y ')}</p>
              {item.observacion && <p className="whitespace-pre-wrap">{item.observacion}</p>}
            </li>)}</ul>
            {historyMore && <Button type="button" variant="secondary" disabled={historyLoading} onClick={() => void moreHistory()}>Ver más</Button>}
          </section>
        </section>
      ) : query.length > 0 && (
        <section aria-label="Coincidencias de kardex" className="space-y-3">
          {results.length > 0 && <p className="text-sm font-semibold text-slate-600">Coincidencias {hasMore ? 'encontradas hasta ahora' : 'encontradas'}: {results.length}</p>}
          <ul className="space-y-2">
            {results.map((location) => (
              <li key={location.id}>
                <button type="button" onClick={() => {
                  setHistory([])
                  setHistoryError('')
                  setHistoryLoading(true)
                  setPhotoVersion(null)
                  setSelected(location)
                }} className="flex w-full items-center gap-4 rounded-2xl bg-white p-3 text-left shadow-sm ring-1 ring-slate-100 transition hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700">
                  <LazyPhoto locationId={location.id} />
                  <span className="min-w-0 flex-1">
                    <span className="block break-all whitespace-pre-wrap font-bold text-slate-900"><Highlight value={location.kardex} query={query} /></span>
                    <VisibleWhitespace value={location.kardex} />
                    <span className="mt-1 block text-sm text-slate-600">Registrado por: {location.creado_por_nombre ?? 'Desconocido'}</span>
                    {location.registro_pendiente && <span className="mt-1 block text-xs font-semibold text-amber-800">Registro pendiente o requiere revisión</span>}
                    <span className="mt-1 block text-xs text-slate-500">Ubicación #{location.id} · {location.latitud === null && !location.url_gps ? 'Sin coordenadas' : 'Con ubicación'}</span>
                  </span>
                  <span aria-hidden="true" className="text-xl text-blue-700">›</span>
                </button>
              </li>
            ))}
          </ul>
          {loading && <p role="status" className="text-sm text-slate-500">Buscando coincidencias...</p>}
          {error && <div role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700"><p>{error}</p><Button type="button" variant="secondary" className="mt-2" onClick={() => { setError(''); setLoading(true); setRetry((value) => value + 1) }}>Reintentar</Button></div>}
          {!loading && !error && results.length === 0 && <p className="rounded-xl bg-blue-50 p-4 text-sm text-blue-900">No se encontraron coincidencias para este kardex.</p>}
          {hasMore && !error && <div ref={sentinel} aria-hidden="true" />}
          {hasMore && !loading && !error && typeof IntersectionObserver === 'undefined' && <Button type="button" variant="secondary" onClick={() => { setLoading(true); setPage((value) => value + 1) }}>Cargar más coincidencias</Button>}
        </section>
      )}
    </div>
  )
}
