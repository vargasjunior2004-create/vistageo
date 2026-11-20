import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { CameraInput } from '../components/CameraInput'
import { Input } from '../components/Input'
import { deleteDraft, getDraft, saveDraft, type LocationDraft } from '../services/localPhotos'
import { encodeOfficialPhoto } from '../services/officialPhoto'
import { googleMapsLink } from '../services/maps'
import type { Location } from '../types/api'

export function FieldLocationPage() {
  const { user, hasPermission } = useAuth()
  const [kardex, setKardex] = useState('')
  const [checked, setChecked] = useState<string | null>(null)
  const [location, setLocation] = useState<Location | null>(null)
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState('')
  const [retryCheck, setRetryCheck] = useState(0)
  const checkController = useRef<AbortController | null>(null)
  const [photo, setPhoto] = useState('')
  const [position, setPosition] = useState<{ latitude: number; longitude: number; accuracy: number; rawLatitude?: string; rawLongitude?: string } | null>(null)
  const [method, setMethod] = useState<'GPS_DISPOSITIVO' | 'ENLACE_COMPARTIDO' | ''>('')
  const [sharedUrl, setSharedUrl] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [draft, setDraft] = useState<LocationDraft | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const allowed = hasPermission('ubicaciones.registrar')

  useEffect(() => {
    if (!user) return
    getDraft(user.id).then((value) => setDraft(value ?? null))
      .catch((err: Error) => setError(err.message))
  }, [user])

  useEffect(() => {
    if (!allowed || draft || !kardex) return
    const controller = new AbortController()
    checkController.current = controller
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ kardex })
      apiRequest<Location[]>(`/ubicaciones?${params}`, { signal: controller.signal, activity: true })
        .then((locations) => {
          if (controller.signal.aborted) return
          setLocation(locations[0] ?? null)
          setChecked(kardex)
        })
        .catch((err: unknown) => {
          if (!controller.signal.aborted) setCheckError(err instanceof Error ? err.message : 'No se pudo consultar el kardex.')
        })
        .finally(() => { if (!controller.signal.aborted) setChecking(false) })
    }, 350)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [allowed, draft, kardex, retryCheck])

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
    setPosition(null)
    setConfirmed(false)
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

  const interpret = async () => {
    setPosition(null)
    setConfirmed(false)
    setError('')
    setBusy(true)
    try {
      const result = await apiRequest<{ latitud: string; longitud: string }>('/registro-ubicacion/interpretar-enlace', {
        method: 'POST', body: { url_gps: sharedUrl },
      })
      setPosition({ latitude: Number(result.latitud), longitude: Number(result.longitud), accuracy: 0, rawLatitude: result.latitud, rawLongitude: result.longitud })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo interpretar el enlace.')
    } finally {
      setBusy(false)
    }
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
      setMethod('')
      setSharedUrl('')
      setConfirmed(false)
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
    if (!user || !position || !photo || !method || !confirmed || checked !== kardex || location) return
    const value: LocationDraft = {
      idempotencia: crypto.randomUUID(), kardex, latitud: position.rawLatitude ?? String(position.latitude),
      longitud: position.rawLongitude ?? String(position.longitude), fotografia_base64: photo,
      metodo_coordenadas: method, url_gps: method === 'ENLACE_COMPARTIDO' ? sharedUrl : null,
      coordenadas_confirmadas: true,
    }
    try {
      await saveDraft(user.id, value)
      setDraft(value)
      await submitDraft(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el borrador local.')
    }
  }

  if (!allowed) return <p>No tienes permiso para esta función.</p>

  const point = draft && !draft.metodo_coordenadas
    ? { latitude: Number(draft.latitud), longitude: Number(draft.longitud) }
    : position
  const mapUrl = point
    ? `https://www.openstreetmap.org/export/embed.html?bbox=${encodeURIComponent([
      Math.max(-180, point.longitude - 0.005), Math.max(-90, point.latitude - 0.005),
      Math.min(180, point.longitude + 0.005), Math.min(90, point.latitude + 0.005),
    ].join(','))}&marker=${encodeURIComponent(`${point.latitude},${point.longitude}`)}`
    : ''

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Link to="/" className="text-sm font-semibold text-blue-700">← Volver al panel</Link>
      <div className="rounded-3xl bg-[#102c50] p-6 text-white">
        <p className="text-sm text-blue-200">VISTA GEO · Ubicación oficial</p>
        <h1 className="mt-1 text-2xl font-bold">Registrar ubicación</h1>
      </div>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-700">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-blue-50 p-3 text-blue-800">{message}</p>}
      {busy && <p role="status" className="rounded-xl bg-blue-50 p-3 text-blue-800">Procesando, espera un momento...</p>}
      {draft ? (
        <div className="space-y-3 rounded-2xl bg-amber-50 p-5">
          <p>Hay un registro pendiente para <strong>{draft.kardex}</strong>. Reintenta con los mismos datos.</p>
          {!draft.metodo_coordenadas && <div className="space-y-3">
            <p>Este borrador anterior no indica el origen. Selecciona cómo obtuviste esas coordenadas y confirma el punto antes de reintentar.</p>
            <label className="block"><input type="radio" name="legacy-method" checked={method === 'GPS_DISPOSITIVO'} onChange={() => { setMethod('GPS_DISPOSITIVO'); setPosition(null); setConfirmed(false) }} /> Capturé esta ubicación con el GPS del dispositivo</label>
            <label className="block"><input type="radio" name="legacy-method" checked={method === 'ENLACE_COMPARTIDO'} onChange={() => { setMethod('ENLACE_COMPARTIDO'); setPosition(null); setConfirmed(false) }} /> Obtuve esta ubicación de un enlace compartido</label>
            {method === 'ENLACE_COMPARTIDO' && <>
              <Input label="Enlace compartido" value={sharedUrl} disabled={busy} onChange={(event) => { setSharedUrl(event.target.value); setPosition(null); setConfirmed(false) }} />
              <Button type="button" variant="secondary" disabled={busy || !sharedUrl} onClick={() => void interpret()}>Comprobar enlace</Button>
              {position && (position.latitude !== Number(draft.latitud) || position.longitude !== Number(draft.longitud)) && <p role="alert">El enlace no coincide con las coordenadas del borrador.</p>}
            </>}
            <p>{draft.latitud}, {draft.longitud}</p>
            <iframe title="Mapa del borrador" src={mapUrl} className="h-64 w-full rounded-xl border-0" loading="lazy" referrerPolicy="no-referrer" />
            <p className="text-xs text-slate-600">El mapa de OpenStreetMap recibe estas coordenadas para mostrar la vista previa.</p>
            <label className="block"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> Confirmo el punto y su origen</label>
          </div>}
          <Button type="button" disabled={busy || (!draft.metodo_coordenadas && (!method || !confirmed || (method === 'ENLACE_COMPARTIDO' && (!position || position.latitude !== Number(draft.latitud) || position.longitude !== Number(draft.longitud)))))} onClick={() => {
            if (draft.metodo_coordenadas) { void submitDraft(draft); return }
            if (!method || !user) return
            const value: LocationDraft = { ...draft, metodo_coordenadas: method, url_gps: method === 'ENLACE_COMPARTIDO' ? sharedUrl : null, coordenadas_confirmadas: true }
            setBusy(true)
            saveDraft(user.id, value).then(() => { setDraft(value); return submitDraft(value) })
              .catch((err: Error) => { setError(err.message); setBusy(false) })
          }}>Reintentar registro</Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={() => {
            if (!user || !window.confirm('Si el servidor recibió el registro, podría quedar pendiente de revisión. ¿Descartar el borrador local?')) return
            deleteDraft(user.id).then(() => setDraft(null)).catch((err: Error) => setError(err.message))
          }}>Descartar borrador local</Button>
        </div>
      ) : (
        <div className="rounded-3xl bg-white p-5 shadow-sm">
          <Input label="Kardex exacto" value={kardex} disabled={busy} onChange={(event) => {
            const value = event.target.value
            checkController.current?.abort()
            setKardex(value); setChecked(null); setLocation(null); setPosition(null); setPhoto(''); setMethod(''); setSharedUrl(''); setConfirmed(false)
            setError(''); setMessage(''); setCheckError(''); setChecking(value.length > 0)
          }} required />
          {checking && <p role="status" className="mt-2 text-sm text-slate-600">Comprobando kardex...</p>}
          {checkError && <div role="alert" className="mt-2 text-sm text-red-700">
            <p>{checkError}</p>
            <Button type="button" variant="secondary" onClick={() => { setCheckError(''); setChecking(true); setRetryCheck((value) => value + 1) }}>Reintentar</Button>
          </div>}
        </div>
      )}
      {!draft && checked !== null && !location && (
        <p className="rounded-xl bg-blue-50 p-4 text-blue-900">Este kardex está disponible para registrar una ubicación.</p>
      )}
      {!draft && location && (
        <div className="space-y-3 rounded-3xl bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Kardex: {location.kardex}</h2>
          {!message && (location.registro_pendiente
            ? <p>Este registro está pendiente o requiere revisión. Si tienes el borrador original, reinténtalo; de lo contrario, contacta a un administrador.</p>
            : <p>Este kardex ya tiene una ubicación. No se creará un duplicado.</p>)}
        </div>
      )}
      {!draft && checked !== null && !location && (
        <div className="space-y-4 rounded-3xl bg-white p-5 shadow-sm">
          <h2 className="font-semibold">Fachada y ubicación</h2>
          <CameraInput disabled={busy} allowGallery onPhoto={(file) => void capture(file)} />
          <fieldset className="space-y-3">
            <legend className="font-semibold">¿Cómo obtendrás la ubicación?</legend>
            <label className={`block cursor-pointer rounded-xl border p-4 ${method === 'GPS_DISPOSITIVO' ? 'border-blue-700 bg-blue-50' : 'border-slate-200'}`}><input type="radio" name="method" disabled={busy} checked={method === 'GPS_DISPOSITIVO'} onChange={() => { setMethod('GPS_DISPOSITIVO'); setPosition(null); setSharedUrl(''); setConfirmed(false) }} /> <strong>Capturar ubicación actual</strong><span className="block pl-5 text-sm text-slate-600">Usa el GPS de este dispositivo en el domicilio.</span></label>
            <label className={`block cursor-pointer rounded-xl border p-4 ${method === 'ENLACE_COMPARTIDO' ? 'border-blue-700 bg-blue-50' : 'border-slate-200'}`}><input type="radio" name="method" disabled={busy} checked={method === 'ENLACE_COMPARTIDO'} onChange={() => { setMethod('ENLACE_COMPARTIDO'); setPosition(null); setConfirmed(false) }} /> <strong>Usar ubicación compartida</strong><span className="block pl-5 text-sm text-slate-600">Pega el enlace recibido del cliente.</span></label>
          </fieldset>
          {method === 'GPS_DISPOSITIVO' && <Button type="button" variant="secondary" disabled={busy} onClick={locate}>Obtener ubicación actual</Button>}
          {method === 'ENLACE_COMPARTIDO' && <div className="space-y-2"><Input label="Enlace GPS compartido" value={sharedUrl} disabled={busy} onChange={(event) => { setSharedUrl(event.target.value); setPosition(null); setConfirmed(false) }} /><Button type="button" variant="secondary" disabled={busy || !sharedUrl} onClick={() => void interpret()}>Interpretar enlace</Button></div>}
          <div className="space-y-2 rounded-2xl bg-slate-50 p-4">
            <h3 className="font-semibold">Resumen antes de guardar</h3>
            <p className="break-all whitespace-pre-wrap text-sm">Kardex: {kardex}</p>
            {photo ? <img className="max-h-72 rounded-xl" src={`data:image/jpeg;base64,${photo}`} alt="Vista previa de fachada" /> : <p className="text-sm text-slate-600">Añade una foto de fachada.</p>}
            {position ? <>
              <p className="text-sm text-slate-600">{position.latitude}, {position.longitude}{method === 'GPS_DISPOSITIVO' && ` · Precisión aproximada: ${Math.round(position.accuracy)} m`}</p>
              <iframe title="Vista previa de ubicación" src={mapUrl} className="h-64 w-full rounded-xl border-0" loading="lazy" referrerPolicy="no-referrer" />
              <p className="text-xs text-slate-500">El mapa de OpenStreetMap recibe estas coordenadas para mostrar la vista previa.</p>
              <a className="block break-all text-sm text-blue-700 underline" href={googleMapsLink(position.latitude, position.longitude)} target="_blank" rel="noopener noreferrer">{googleMapsLink(position.latitude, position.longitude)}</a>
              <label className="block text-sm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> Confirmo que este punto corresponde al domicilio.</label>
            </> : <p className="text-sm text-slate-600">Selecciona un método y obtén las coordenadas.</p>}
          </div>
          <Button type="button" disabled={busy || !photo || !position || !method || !confirmed} onClick={() => void register()}>Confirmar registro</Button>
        </div>
      )}
    </div>
  )
}
