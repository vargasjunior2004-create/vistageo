import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import { LocationPhoto } from '../components/LocationPhoto'
import { ReplaceLocationPhoto } from '../components/ReplaceLocationPhoto'
import { googleMapsLink } from '../services/maps'
import type { Location, LocationRevision } from '../types/api'

const PAGE_SIZE = 25
const DEBOUNCE_MS = 350

function mapsLink(revision: LocationRevision | null): string | null {
  if (!revision) return null
  if (revision.latitud !== null && revision.longitud !== null) {
    return googleMapsLink(revision.latitud, revision.longitud)
  }
  if (!revision.url_gps) return null
  try {
    const url = new URL(revision.url_gps)
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
  const [revision, setRevision] = useState<LocationRevision | null>(null)
  const [revisionLoading, setRevisionLoading] = useState(false)
  const [revisionError, setRevisionError] = useState('')
  const [photoVersion, setPhotoVersion] = useState<string | null>(null)
  const [photoRevision, setPhotoRevision] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  const detail = useRef<HTMLElement>(null)

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
    if (!selected) return
    detail.current?.focus()
    if (selected.revision_actual_id === null) return
    const controller = new AbortController()
    const params = new URLSearchParams({ revision_id: String(selected.revision_actual_id) })
    apiRequest<LocationRevision[]>(`/ubicaciones/${selected.id}/revisiones?${params}`, { signal: controller.signal, activity: true })
      .then((items) => {
        if (controller.signal.aborted) return
        const current = items.find((item) => item.id === selected.revision_actual_id)
        if (current) setRevision(current)
        else setRevisionError('La revisión vigente no está disponible.')
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setRevisionError(err instanceof Error ? err.message : 'No se pudo cargar la ubicación.')
      })
      .finally(() => { if (!controller.signal.aborted) setRevisionLoading(false) })
    return () => controller.abort()
  }, [selected])

  if (!allowed) return <p>No tienes permiso para esta función.</p>
  const link = mapsLink(revision)

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
      </div>
      {selected ? (
        <section ref={detail} tabIndex={-1} className="space-y-4 rounded-3xl bg-white p-5 shadow-sm outline-none">
          <button type="button" className="text-sm font-semibold text-blue-700 focus-visible:outline-2 focus-visible:outline-offset-2" onClick={() => setSelected(null)}>← Volver a coincidencias</button>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Kardex · Ubicación #{selected.id}</p>
            <h2 className="mt-1 break-all whitespace-pre-wrap text-xl font-bold text-slate-900">{selected.kardex}</h2>
            <p className="mt-2 text-sm text-slate-600">Registrado por: {selected.creado_por_nombre ?? 'Desconocido'}</p>
            <p className="text-sm text-slate-600">Fecha de registro: {selected.creado_en ? new Date(selected.creado_en).toLocaleString() : 'Desconocida'}</p>
          </div>
          <LocationPhoto key={`${selected.id}-${photoRevision}`} locationId={selected.id} onVersion={setPhotoVersion} />
          {user && hasPermission('ubicaciones.fotografia.editar') && <ReplaceLocationPhoto
            key={selected.id}
            userId={user.id}
            locationId={selected.id}
            version={photoVersion}
            onUpdated={() => { setPhotoVersion(null); setPhotoRevision((value) => value + 1) }}
          />}
          {revisionLoading && <p role="status" className="text-sm text-slate-500">Cargando ubicación...</p>}
          {revisionError && <p role="alert" className="text-sm text-red-700">{revisionError}</p>}
          {!revisionLoading && !revisionError && (revision
            ? <p className="text-sm text-slate-600">{revision.latitud ?? '—'}, {revision.longitud ?? '—'}</p>
            : <p className="text-sm text-slate-600">No hay coordenadas o enlace GPS vigente.</p>)}
          {revision?.url_gps && <p className="break-all text-sm text-slate-600">URL GPS: {revision.url_gps}</p>}
          {link && <><p className="break-all text-sm text-slate-600">Enlace: {link}</p><a className="inline-block rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white" href={link} target="_blank" rel="noopener noreferrer">Abrir ubicación</a></>}
        </section>
      ) : query.length > 0 && (
        <section aria-label="Coincidencias de kardex" className="space-y-3">
          {results.length > 0 && <p className="text-sm font-semibold text-slate-600">Coincidencias {hasMore ? 'encontradas hasta ahora' : 'encontradas'}: {results.length}</p>}
          <ul className="space-y-2">
            {results.map((location) => (
              <li key={location.id}>
                <button type="button" onClick={() => {
                  setRevision(null)
                  setRevisionError('')
                  setRevisionLoading(location.revision_actual_id !== null)
                  setPhotoVersion(null)
                  setSelected(location)
                }} className="flex w-full items-center gap-4 rounded-2xl bg-white p-3 text-left shadow-sm ring-1 ring-slate-100 transition hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700">
                  <LazyPhoto locationId={location.id} />
                  <span className="min-w-0 flex-1">
                    <span className="block break-all whitespace-pre-wrap font-bold text-slate-900"><Highlight value={location.kardex} query={query} /></span>
                    <span className="mt-1 block text-sm text-slate-600">Registrado por: {location.creado_por_nombre ?? 'Desconocido'}</span>
                    <span className="mt-1 block text-xs text-slate-500">Ubicación #{location.id} · {location.revision_actual_id === null ? 'Sin revisión vigente' : 'Con revisión vigente'}</span>
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
