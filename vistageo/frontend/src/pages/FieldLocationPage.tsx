import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { CameraInput } from '../components/CameraInput'
import { Input } from '../components/Input'
import { LocationPhoto } from '../components/LocationPhoto'
import { deleteDraft, getDraft, saveDraft, type LocationDraft } from '../services/localPhotos'
import { encodeOfficialPhoto } from '../services/officialPhoto'
import type { Contract, Location, LocationRevision } from '../types/api'

function mapsLink(revision: LocationRevision | null): string | null {
  if (!revision) return null
  if (revision.latitud !== null && revision.longitud !== null) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${revision.latitud},${revision.longitud}`)}`
  }
  if (!revision.url_gps) return null
  try {
    const url = new URL(revision.url_gps)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

export function FieldLocationPage({ mode }: { mode: 'register' | 'search' }) {
  const { user, hasPermission } = useAuth()
  const [kardex, setKardex] = useState('')
  const [checked, setChecked] = useState<string | null>(null)
  const [location, setLocation] = useState<Location | null>(null)
  const [revision, setRevision] = useState<LocationRevision | null>(null)
  const [contractExists, setContractExists] = useState(false)
  const [photo, setPhoto] = useState('')
  const [position, setPosition] = useState<{ latitude: number; longitude: number; accuracy: number } | null>(null)
  const [draft, setDraft] = useState<LocationDraft | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const permission = mode === 'register' ? 'ubicaciones.registrar' : 'ubicaciones.consultar'

  useEffect(() => {
    if (mode !== 'register' || !user) return
    getDraft(user.id).then((value) => setDraft(value ?? null))
      .catch((err: Error) => setError(err.message))
  }, [mode, user])

  const search = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    setMessage('')
    setChecked(null)
    setLocation(null)
    setRevision(null)
    setBusy(true)
    try {
      const params = new URLSearchParams({ kardex })
      const [locations, contracts] = await Promise.all([
        apiRequest<Location[]>(`/ubicaciones?${params}`, { activity: true }),
        apiRequest<Contract[]>(`/contratos?${params}`, { activity: true }),
      ])
      const found = locations[0] ?? null
      setLocation(found)
      setContractExists(contracts.length > 0)
      setChecked(kardex)
      if (mode === 'search' && found?.revision_actual_id !== null && found) {
        const revisions = await apiRequest<LocationRevision[]>(`/ubicaciones/${found.id}/revisiones?revision_id=${found.revision_actual_id}`)
        setRevision(revisions.find((item) => item.id === found.revision_actual_id) ?? null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo consultar el kardex.')
    } finally {
      setBusy(false)
    }
  }

  const capture = async (file: File) => {
    setError('')
    setBusy(true)
    try {
      setPhoto(await encodeOfficialPhoto(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo preparar la fotografía.')
    } finally {
      setBusy(false)
    }
  }

  const locate = () => {
    setError('')
    if (!navigator.geolocation) {
      setError('Este dispositivo no dispone de ubicación GPS.')
      return
    }
    setBusy(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setPosition({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy })
        setBusy(false)
      },
      (err) => {
        setError(err.code === err.PERMISSION_DENIED ? 'Permite el acceso a la ubicación para continuar.' : 'No se pudo obtener el GPS. Inténtalo nuevamente.')
        setBusy(false)
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 },
    )
  }

  const submitDraft = async (value: LocationDraft) => {
    if (!user) return
    setBusy(true)
    setError('')
    try {
      const result = await apiRequest<Location>('/registro-ubicacion', { method: 'POST', body: value })
      setLocation(result)
      setChecked(value.kardex)
      setPhoto('')
      setPosition(null)
      setMessage('Ubicación y fotografía registradas correctamente.')
      try {
        await deleteDraft(user.id)
        setDraft(null)
      } catch {
        setError('El registro se completó, pero no se pudo eliminar el borrador local. Puedes reintentarlo sin duplicar la ubicación.')
      }
    } catch (err) {
      setError(err instanceof Error ? `${err.message}. Conserva el borrador y vuelve a intentar.` : 'No se pudo registrar la ubicación.')
    } finally {
      setBusy(false)
    }
  }

  const register = async () => {
    if (!user || !position || !photo || checked !== kardex || location) return
    const value: LocationDraft = {
      idempotencia: crypto.randomUUID(), kardex, latitud: String(position.latitude),
      longitud: String(position.longitude), fotografia_base64: photo,
    }
    try {
      await saveDraft(user.id, value)
      setDraft(value)
      await submitDraft(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el borrador local.')
    }
  }

  if (!hasPermission(permission)) return <p>No tienes permiso para esta función.</p>
  const link = mapsLink(revision)

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link to="/" className="text-sm font-semibold text-blue-700">← Volver al panel</Link>
      <div className="rounded-3xl bg-[#102c50] p-6 text-white">
        <p className="text-sm text-blue-200">VISTA GEO · Ubicación oficial</p>
        <h1 className="mt-1 text-2xl font-bold">{mode === 'register' ? 'Registrar ubicación' : 'Consultar ubicación'}</h1>
      </div>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-700">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-blue-50 p-3 text-blue-800">{message}</p>}
      {draft && mode === 'register' ? (
        <div className="space-y-3 rounded-2xl bg-amber-50 p-5">
          <p>Hay un registro pendiente para <strong>{draft.kardex}</strong>. Reintenta con los mismos datos.</p>
          <Button type="button" disabled={busy} onClick={() => void submitDraft(draft)}>Reintentar registro</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => {
            if (!user || !window.confirm('Si el servidor recibió el registro, podría quedar pendiente de revisión. ¿Descartar el borrador local?')) return
            deleteDraft(user.id).then(() => setDraft(null)).catch((err: Error) => setError(err.message))
          }}>Descartar borrador local</Button>
        </div>
      ) : (
        <form onSubmit={search} className="flex flex-wrap items-end gap-3 rounded-3xl bg-white p-5 shadow-sm">
          <div className="min-w-0 flex-1"><Input label="Kardex exacto" value={kardex} onChange={(event) => {
            setKardex(event.target.value); setChecked(null); setLocation(null); setPosition(null); setPhoto('')
          }} required /></div>
          <Button type="submit" disabled={busy}>Consultar</Button>
        </form>
      )}
      {!draft && checked !== null && !location && (
        <p className="rounded-xl bg-blue-50 p-4 text-blue-900">
          {mode === 'register' ? (contractExists ? 'Contrato encontrado. Puedes registrar su ubicación.' : 'Contrato nuevo: se creará al confirmar.') : 'No se encontró una ubicación para este kardex.'}
        </p>
      )}
      {!draft && location && (
        <div className="space-y-3 rounded-3xl bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Kardex: {location.kardex}</h2>
          {mode === 'register' ? <p>Este kardex ya tiene una ubicación. No se creará un duplicado.</p> : <>
            <LocationPhoto key={location.id} locationId={location.id} />
            {revision ? <p className="text-sm">{revision.latitud ?? '—'}, {revision.longitud ?? '—'}</p> : <p>No hay coordenadas o enlace GPS vigente.</p>}
            {link && <a className="inline-block rounded-xl bg-blue-700 px-4 py-3 font-semibold text-white" href={link} target="_blank" rel="noopener noreferrer">Abrir ubicación</a>}
          </>}
        </div>
      )}
      {mode === 'register' && !draft && checked !== null && !location && (
        <div className="space-y-4 rounded-3xl bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Fachada y ubicación GPS</h2>
          <CameraInput disabled={busy} onPhoto={(file) => void capture(file)} />
          {photo && <img className="max-h-72 rounded-xl" src={`data:image/jpeg;base64,${photo}`} alt="Vista previa de fachada" />}
          <div><Button type="button" variant="secondary" disabled={busy} onClick={locate}>Obtener GPS</Button></div>
          {position && <p className="text-sm text-slate-600">{position.latitude}, {position.longitude} · Precisión aproximada: {Math.round(position.accuracy)} m</p>}
          <Button type="button" disabled={busy || !photo || !position} onClick={() => void register()}>Confirmar registro</Button>
        </div>
      )}
    </div>
  )
}
