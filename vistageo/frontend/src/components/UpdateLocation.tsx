import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import {
  deletePhotoDraft, deleteUpdateDraft, getPhotoDraft, getUpdateDraft, saveUpdateDraft,
  type LocationUpdateBody, type LocationUpdateDraft, type PhotoReplacementDraft,
} from '../services/localPhotos'
import { encodeOfficialPhoto } from '../services/officialPhoto'
import type { Location, UpdateReason } from '../types/api'
import { Button } from './Button'
import { CameraInput } from './CameraInput'
import { GpsCapture } from './GpsCapture'
import type { GpsPosition } from '../services/gpsCapture'

type Props = {
  userId: number
  location: Location
  photoVersion: string | null
  canPhoto: boolean
  canGps: boolean
  onUpdated: () => void
}

export function UpdateLocation({ userId, location, photoVersion, canPhoto, canGps, onUpdated }: Props) {
  const [draft, setDraft] = useState<LocationUpdateDraft | null>(null)
  const [legacy, setLegacy] = useState<PhotoReplacementDraft | null>(null)
  const [loading, setLoading] = useState(true)
  const [draftsUnavailable, setDraftsUnavailable] = useState(false)
  const [canDiscard, setCanDiscard] = useState(false)
  const [editing, setEditing] = useState(false)
  const [reasons, setReasons] = useState<UpdateReason[]>([])
  const [reasonId, setReasonId] = useState('')
  const [observation, setObservation] = useState('')
  const [photo, setPhoto] = useState('')
  const [position, setPosition] = useState<GpsPosition | null>(null)
  const [capturingGps, setCapturingGps] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([getUpdateDraft(userId, location.id), getPhotoDraft(userId, location.id)])
      .then(([saved, old]) => { if (active) { setDraft(saved ?? null); setLegacy(old ?? null) } })
      .catch((err: unknown) => { if (active) { setDraftsUnavailable(true); setError(err instanceof Error ? err.message : 'No se pudieron consultar los borradores.') } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [userId, location.id])

  const open = async () => {
    setError('')
    setBusy(true)
    try {
      setReasons(await apiRequest<UpdateReason[]>('/motivos-actualizacion'))
      setEditing(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudieron cargar los motivos.')
    } finally {
      setBusy(false)
    }
  }

  const capture = async (file: File) => {
    setBusy(true)
    setError('')
    try { setPhoto(await encodeOfficialPhoto(file)) }
    catch (err) { setError(err instanceof Error ? err.message : 'No se pudo preparar la fotografía.') }
    finally { setBusy(false) }
  }

  const submit = async (value: LocationUpdateDraft) => {
    setBusy(true)
    setError('')
    setMessage('')
    setCanDiscard(false)
    try {
      const result = await apiRequest<{ estado: string }>(`/ubicaciones/${location.id}/actualizacion`, { method: 'PUT', body: value.body })
      if (result.estado !== 'finalizada' && result.estado !== 'pendiente_limpieza') throw new Error('El servidor devolvió un estado desconocido.')
      onUpdated()
      if (result.estado === 'pendiente_limpieza') {
        setMessage('Los cambios están guardados. La eliminación de la foto anterior sigue pendiente; reintenta.')
      } else {
        if (value.legacy) {
          await deletePhotoDraft(userId, location.id)
          setLegacy(null)
        }
        await deleteUpdateDraft(userId, location.id)
        setDraft(null)
        setEditing(false)
        setPhoto('')
        setPosition(null)
        setCapturingGps(false)
        setMessage('Ubicación actualizada correctamente.')
      }
    } catch (err) {
      if (err instanceof Error && 'status' in err && (err.status === 412 || err.status === 422) && !value.body.fotografia_base64) setCanDiscard(true)
      setError(err instanceof Error ? `${err.message}. Conserva el borrador y reintenta.` : 'No se pudo actualizar; conserva el borrador.')
    } finally {
      setBusy(false)
    }
  }

  const retryLegacy = async () => {
    if (!legacy) return
    setBusy(true)
    setError('')
    try {
      const result = await apiRequest<{ estado: string }>(`/ubicaciones/${location.id}/fotografia`, { method: 'PUT', body: legacy })
      onUpdated()
      if (result.estado === 'finalizada') {
        await deletePhotoDraft(userId, location.id)
        setLegacy(null)
        setMessage('Reemplazo anterior completado.')
      } else if (result.estado === 'pendiente_limpieza') {
        setMessage('El reemplazo anterior está guardado, pero la limpieza sigue pendiente.')
      } else throw new Error('El servidor devolvió un estado desconocido.')
    } catch (err) {
      setError(err instanceof Error ? `${err.message}. Si aún no se publicó, selecciónalo con un motivo.` : 'No se pudo recuperar el reemplazo.')
    } finally { setBusy(false) }
  }

  const confirm = async () => {
    if (!reasonId || (!photo && !position && !legacy) || (position && !position.acceptable)) return
    if ((photo || legacy) && !window.confirm('La foto anterior se eliminará de Storage. ¿Confirmas el reemplazo?')) return
    const body: LocationUpdateBody = {
      idempotencia: legacy?.idempotencia ?? crypto.randomUUID(), version: location.version,
      motivo_id: Number(reasonId), observacion: observation.trim() || null,
    }
    if (position) {
      body.latitud = String(position.latitude); body.longitud = String(position.longitude)
      body.precision_metros = position.accuracy; body.capturado_en = position.capturedAt
    }
    if (legacy) { body.fotografia_base64 = legacy.fotografia_base64; body.foto_version = legacy.version }
    else if (photo && photoVersion) { body.fotografia_base64 = photo; body.foto_version = photoVersion }
    if (!body.fotografia_base64 && !body.latitud) return
    const value = { body, legacy: !!legacy }
    setBusy(true)
    setError('')
    try {
      await saveUpdateDraft(userId, location.id, value)
      setDraft(value)
      await submit(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el borrador local.')
      setBusy(false)
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Comprobando actualizaciones pendientes...</p>
  if (draftsUnavailable) return <p role="alert" className="text-sm text-red-700">{error}</p>
  return <section className="space-y-3 border-t border-slate-100 pt-4">
    {message && <p role="status" className="text-sm text-blue-800">{message}</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {draft ? <>
      <p className="text-sm text-amber-800">Hay una actualización pendiente. Reintenta con los mismos datos.</p>
      <Button type="button" disabled={busy} onClick={() => void submit(draft)}>Reintentar actualización</Button>
      {canDiscard && <Button type="button" variant="secondary" disabled={busy} onClick={() => {
        setBusy(true)
        deleteUpdateDraft(userId, location.id)
          .then(() => { setDraft(null); setCanDiscard(false); setError(''); onUpdated() })
          .catch((err: unknown) => setError(err instanceof Error ? err.message : 'No se pudo eliminar el borrador.'))
          .finally(() => setBusy(false))
      }}>Descartar borrador desactualizado</Button>}
    </> : legacy && !editing ? <>
      <p className="text-sm text-amber-800">Hay un reemplazo anterior pendiente. Reintenta su limpieza o complétalo seleccionando un motivo.</p>
      <Button type="button" variant="secondary" disabled={busy} onClick={() => void retryLegacy()}>Reintentar reemplazo anterior</Button>{' '}
      {canPhoto && <Button type="button" disabled={busy} onClick={() => void open()}>Completar con motivo</Button>}
    </> : editing ? <>
      {legacy && <p className="text-sm text-slate-600">Se utilizará la fotografía del borrador anterior.</p>}
      {!legacy && canPhoto && photoVersion && <><p className="text-sm text-slate-600">Selecciona una nueva fachada si deseas reemplazarla.</p>
        <CameraInput allowGallery disabled={busy} onPhoto={(file) => void capture(file)} />
        {photo && <img className="max-h-48 rounded-xl" src={`data:image/jpeg;base64,${photo}`} alt="Vista previa de nueva fachada" />}</>}
      {canGps && (capturingGps
        ? <GpsCapture disabled={busy} onChange={setPosition} />
        : <Button type="button" variant="secondary" disabled={busy} onClick={() => setCapturingGps(true)}>Capturar nueva ubicación GPS</Button>)}
      <label className="block text-sm font-medium text-slate-700">Motivo de actualización
        <select value={reasonId} onChange={(event) => setReasonId(event.target.value)} className="mt-1 block min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-[#2f6ecb] focus:outline-none focus:ring-2 focus:ring-[#2f6ecb]/15" required>
          <option value="">Selecciona un motivo</option>{reasons.map((reason) => <option key={reason.id} value={reason.id}>{reason.nombre}</option>)}
        </select>
      </label>
      {reasons.length === 0 && <p className="text-sm text-amber-800">No hay motivos activos. Solicita uno a un administrador.</p>}
      <label className="block text-sm font-medium text-slate-700">Observación opcional
        <textarea value={observation} maxLength={2000} onChange={(event) => setObservation(event.target.value)} className="mt-1 block min-h-24 w-full rounded-lg border border-slate-300 p-3 text-sm focus:border-[#2f6ecb] focus:outline-none focus:ring-2 focus:ring-[#2f6ecb]/15" />
      </label>
      <div className="flex flex-wrap gap-2"><Button type="button" disabled={busy || !reasonId || (!photo && !position && !legacy) || (!!position && !position.acceptable)} onClick={() => void confirm()}>Guardar actualización</Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => { setEditing(false); setPhoto(''); setPosition(null); setCapturingGps(false); setError('') }}>Cancelar</Button></div>
    </> : <Button type="button" variant="secondary" disabled={busy || (!canGps && (!canPhoto || !photoVersion))} onClick={() => void open()}>Actualizar fachada o GPS</Button>}
  </section>
}
