import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { CameraInput } from '../components/CameraInput'
import { Input } from '../components/Input'
import { notifications } from '../services/notifications'
import { GpsCapture, type GpsCaptureHandle } from '../components/GpsCapture'
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
  const [checkError, setCheckError] = useState(false)
  const [retryCheck, setRetryCheck] = useState(0)
  const checkController = useRef<AbortController | null>(null)
  const [photo, setPhoto] = useState('')
  const [position, setPosition] = useState<{ latitude: number; longitude: number; accuracy: number | null; capturedAt: string | null; acceptable: boolean; rawLatitude?: string; rawLongitude?: string } | null>(null)
  const [method, setMethod] = useState<'GPS_DISPOSITIVO' | 'ENLACE_COMPARTIDO' | ''>('')
  const [sharedUrl, setSharedUrl] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const gpsCapture = useRef<GpsCaptureHandle>(null)
  const [draft, setDraft] = useState<LocationDraft | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
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
          if (locations[0]) {
            notifications.warning('Este kardex ya tiene una ubicación registrada', 'consulta-kardex')
          } else {
            notifications.success('Kardex disponible para registrar ubicación', 'consulta-kardex')
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            setCheckError(true)
            notifications.error('No se pudo consultar el kardex. Inténtalo nuevamente', 'consulta-kardex')
          }
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

  const interpret = async () => {
    setPosition(null)
    setConfirmed(false)
    setError('')
    setBusy(true)
    try {
      const result = await apiRequest<{ latitud: string; longitud: string }>('/registro-ubicacion/interpretar-enlace', {
        method: 'POST', body: { url_gps: sharedUrl },
      })
      setPosition({ latitude: Number(result.latitud), longitude: Number(result.longitud), accuracy: null, capturedAt: null, acceptable: true, rawLatitude: result.latitud, rawLongitude: result.longitud })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo interpretar el enlace.')
    } finally {
      setBusy(false)
    }
  }

  const submitDraft = async (value: LocationDraft) => {
    if (!user) return
    setBusy(true)
    setSaving(true)
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
      if (err instanceof Error && 'status' in err && err.status === 422 && value.metodo_coordenadas === 'GPS_DISPOSITIVO' && value.precision_metros == null) {
        setError('El borrador anterior no tiene precisión y no se puede crear como un registro nuevo. Si el servidor no lo recibió, descártalo y realiza una nueva captura.')
      } else {
        setError(err instanceof Error ? `${err.message}. Conserva el borrador y vuelve a intentar.` : 'No se pudo registrar la ubicación.')
      }
    } finally {
      setBusy(false)
      setSaving(false)
    }
  }

  const register = async () => {
    if (busy || !user || !position || !position.acceptable || !photo || !method || !confirmed || checked !== kardex || location) return
    const value: LocationDraft = {
      idempotencia: crypto.randomUUID(), kardex, latitud: position.rawLatitude ?? String(position.latitude),
      longitud: position.rawLongitude ?? String(position.longitude), fotografia_base64: photo,
      metodo_coordenadas: method, url_gps: method === 'ENLACE_COMPARTIDO' ? sharedUrl : null,
      coordenadas_confirmadas: true,
      precision_metros: position.accuracy, capturado_en: position.capturedAt,
    }
    setBusy(true)
    setSaving(true)
    setError('')
    try {
      await saveDraft(user.id, value)
      setDraft(value)
      await submitDraft(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el borrador local.')
      setBusy(false)
      setSaving(false)
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
      <header className="space-y-1">
        <p className="text-sm font-medium text-[#2f6ecb]">Ubicación oficial</p>
        <h1 className="page-title">Registrar ubicación</h1>
      </header>
      {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-red-700">{error}</p>}
      {message && <p role="status" className="rounded-xl bg-blue-50 p-3 text-blue-800">{message}</p>}
      {busy && <p role="status" className="rounded-xl bg-blue-50 p-3 text-blue-800">{saving ? 'Guardando domicilio...' : 'Procesando, espera un momento...'}</p>}
      {draft ? (
        <div className="surface-panel space-y-3 border-amber-200 bg-amber-50 p-5">
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
        <div className="surface-panel p-5">
          <Input label="Kardex exacto" value={kardex} disabled={busy} onChange={(event) => {
            const value = event.target.value
            checkController.current?.abort()
            notifications.dismiss('consulta-kardex')
            setKardex(value); setChecked(null); setLocation(null); setPosition(null); setPhoto(''); setMethod(''); setSharedUrl(''); setConfirmed(false)
            setError(''); setMessage(''); setCheckError(false); setChecking(value.length > 0)
          }} required />
          {checking && <p role="status" className="mt-2 text-sm text-slate-600">Comprobando kardex...</p>}
          {checkError && <div className="mt-2">
            <Button type="button" variant="secondary" onClick={() => { notifications.dismiss('consulta-kardex'); setCheckError(false); setChecking(true); setRetryCheck((value) => value + 1) }}>Reintentar consulta</Button>
          </div>}
        </div>
      )}
      {!draft && location && (
        <div className="surface-panel space-y-3 p-5">
          <h2 className="font-semibold">Kardex: {location.kardex}</h2>
          {!message && !location.registro_pendiente && <span className="inline-block rounded-md bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">Ubicación registrada</span>}
          {!message && location.registro_pendiente && <p>Este registro está pendiente o requiere revisión. Si tienes el borrador original, reinténtalo; de lo contrario, contacta a un administrador.</p>}
        </div>
      )}
      {!draft && checked !== null && !location && (
        <div className="surface-panel space-y-4 p-5">
          <h2 className="font-semibold">Fachada y ubicación</h2>
          <CameraInput disabled={busy} allowGallery onPhoto={(file) => void capture(file)} />
          <fieldset className="space-y-3">
            <legend className="font-semibold">¿Cómo obtendrás la ubicación?</legend>
            <label className={`block cursor-pointer rounded-lg border p-4 ${method === 'GPS_DISPOSITIVO' ? 'border-blue-700 bg-blue-50' : 'border-slate-200'}`}><input type="radio" name="method" disabled={busy} checked={method === 'GPS_DISPOSITIVO'} onChange={() => { setMethod('GPS_DISPOSITIVO'); setPosition(null); setSharedUrl(''); setConfirmed(false) }} /> <strong className="font-medium">Capturar ubicación actual</strong><span className="block pl-5 text-sm text-slate-600">Usa el GPS de este dispositivo en el domicilio.</span></label>
            <label className={`block cursor-pointer rounded-lg border p-4 ${method === 'ENLACE_COMPARTIDO' ? 'border-blue-700 bg-blue-50' : 'border-slate-200'}`}><input type="radio" name="method" disabled={busy} checked={method === 'ENLACE_COMPARTIDO'} onChange={() => { setMethod('ENLACE_COMPARTIDO'); setPosition(null); setConfirmed(false) }} /> <strong className="font-medium">Usar ubicación compartida</strong><span className="block pl-5 text-sm text-slate-600">Pega el enlace recibido del cliente.</span></label>
          </fieldset>
          {method === 'GPS_DISPOSITIVO' && !confirmed && <GpsCapture ref={gpsCapture} disabled={saving} onChange={setPosition} />}
          {method === 'ENLACE_COMPARTIDO' && <div className="space-y-2"><Input label="Enlace GPS compartido" value={sharedUrl} disabled={busy} onChange={(event) => { setSharedUrl(event.target.value); setPosition(null); setConfirmed(false) }} /><Button type="button" variant="secondary" disabled={busy || !sharedUrl} onClick={() => void interpret()}>Interpretar enlace</Button></div>}
          <div className="surface-inset space-y-2 p-4">
            <h3 className="font-semibold">Resumen antes de guardar</h3>
            <p className="break-all whitespace-pre-wrap text-sm">Kardex: {kardex}</p>
            {photo ? <img className="max-h-72 rounded-xl" src={`data:image/jpeg;base64,${photo}`} alt="Vista previa de fachada" /> : <p className="text-sm text-slate-600">Añade una foto de fachada.</p>}
            {position ? <>
              <p className="text-sm text-slate-600">{position.latitude}, {position.longitude}{method === 'ENLACE_COMPARTIDO' && ' · Precisión no disponible'}</p>
              <iframe title="Vista previa de ubicación" src={mapUrl} className="h-64 w-full rounded-xl border-0" loading="lazy" referrerPolicy="no-referrer" />
              <p className="text-xs text-slate-500">El mapa de OpenStreetMap recibe estas coordenadas para mostrar la vista previa.</p>
              <a className="block break-all text-sm text-blue-700 underline" href={googleMapsLink(position.latitude, position.longitude)} target="_blank" rel="noopener noreferrer">{googleMapsLink(position.latitude, position.longitude)}</a>
              {confirmed ? <div className="space-y-2">
                <p role="status" className="text-sm font-medium text-green-700">Punto confirmado{position.accuracy !== null ? ` · Precisión: ${position.accuracy} m` : ''}.</p>
                <Button type="button" variant="secondary" disabled={busy} onClick={() => { setConfirmed(false); setPosition(null) }}>
                  {method === 'GPS_DISPOSITIVO' ? 'Buscar otra ubicación' : 'Cambiar ubicación'}
                </Button>
              </div> : <Button type="button" variant="secondary" disabled={busy || !position.acceptable} onClick={() => {
                gpsCapture.current?.stop()
                setConfirmed(true)
              }}>Confirmar este punto</Button>}
            </> : <p className="text-sm text-slate-600">Selecciona un método y obtén las coordenadas.</p>}
          </div>
          {confirmed && !photo && <p className="text-sm text-slate-600">Añade una foto de fachada para guardar el domicilio.</p>}
          <Button type="button" disabled={busy || !photo || !position || !position.acceptable || !method || !confirmed} onClick={() => void register()}>{saving ? 'Guardando domicilio...' : 'Guardar domicilio'}</Button>
        </div>
      )}
    </div>
  )
}
