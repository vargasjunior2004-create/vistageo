import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { deletePhotoDraft, getPhotoDraft, savePhotoDraft, type PhotoReplacementDraft } from '../services/localPhotos'
import { encodeOfficialPhoto } from '../services/officialPhoto'
import { Button } from './Button'
import { CameraInput } from './CameraInput'
import { SkeletonText } from './Skeleton'

type Props = {
  userId: number
  locationId: number
  version: string | null
  onUpdated: () => void
}

export function ReplaceLocationPhoto({ userId, locationId, version, onUpdated }: Props) {
  const [draft, setDraft] = useState<PhotoReplacementDraft | null>(null)
  const [loadingDraft, setLoadingDraft] = useState(true)
  const [draftError, setDraftError] = useState('')
  const [editing, setEditing] = useState(false)
  const [photo, setPhoto] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getPhotoDraft(userId, locationId)
      .then((saved) => { if (active) setDraft(saved ?? null) })
      .catch((err: unknown) => { if (active) setDraftError(err instanceof Error ? err.message : 'No se pudo consultar el borrador local.') })
      .finally(() => { if (active) setLoadingDraft(false) })
    return () => { active = false }
  }, [userId, locationId])

  const capture = async (file: File) => {
    setBusy(true)
    setError('')
    try {
      setPhoto(await encodeOfficialPhoto(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo preparar la fotografía.')
    } finally {
      setBusy(false)
    }
  }

  const submit = async (value: PhotoReplacementDraft) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const result = await apiRequest<{ estado: 'finalizada' | 'pendiente_limpieza' }>(
        `/ubicaciones/${locationId}/fotografia`, { method: 'PUT', body: value },
      )
      if (result.estado !== 'finalizada' && result.estado !== 'pendiente_limpieza') {
        throw new Error('El servidor devolvió un estado de reemplazo desconocido')
      }
      onUpdated()
      if (result.estado === 'pendiente_limpieza') {
        setMessage('La foto nueva está guardada. La eliminación de la anterior sigue pendiente; puedes reintentar.')
      } else {
        try {
          await deletePhotoDraft(userId, locationId)
          setDraft(null)
          setPhoto('')
          setEditing(false)
          setMessage('Foto reemplazada y copia anterior eliminada.')
        } catch {
          setError('La foto se reemplazó, pero no se pudo eliminar el borrador local. Reintenta para limpiarlo.')
        }
      }
    } catch (err) {
      if (err instanceof Error && 'status' in err && err.status === 412) {
        try {
          await deletePhotoDraft(userId, locationId)
          setDraft(null)
          setPhoto('')
          setEditing(false)
          onUpdated()
          setError('La fotografía cambió. Revisa la versión actual antes de volver a reemplazarla.')
        } catch {
          setError('La fotografía cambió y no se pudo limpiar el borrador local. Reintenta.')
        }
      } else {
        setError(err instanceof Error ? `${err.message}. Conserva el borrador y reintenta.` : 'No se pudo reemplazar la fotografía. Conserva el borrador y reintenta.')
      }
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!version || !photo || !window.confirm('La foto anterior se eliminará definitivamente de Storage. ¿Confirmas el reemplazo?')) return
    const value = { idempotencia: crypto.randomUUID(), version, fotografia_base64: photo }
    setBusy(true)
    setError('')
    try {
      await savePhotoDraft(userId, locationId, value)
      setDraft(value)
      await submit(value)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el borrador local.')
      setBusy(false)
    }
  }

  if (loadingDraft) return <div role="status" aria-label="Comprobando reemplazos pendientes"><SkeletonText lines={2} /></div>
  if (draftError) return <p role="alert" className="alert alert-error">{draftError}</p>
  return (
    <div className="space-y-3 border-t border-slate-100 pt-4">
      {busy && <p role="status" className="text-sm text-slate-500">Procesando fotografía...</p>}
      {message && <p role="status" className="text-sm text-blue-800">{message}</p>}
      {error && <p role="alert" className="alert alert-error">{error}</p>}
      {draft ? <>
        <p className="text-sm text-amber-800">Hay un reemplazo pendiente para esta ubicación. Reintenta con la misma foto.</p>
        <img className="max-h-48 rounded-xl" src={`data:image/jpeg;base64,${draft.fotografia_base64}`} alt="Foto pendiente de reemplazo" />
        <Button type="button" disabled={busy} onClick={() => void submit(draft)}>Reintentar reemplazo</Button>
      </> : editing ? <>
        <p className="text-sm text-slate-600">Elige una nueva fachada y revisa la vista previa antes de confirmar.</p>
        <CameraInput allowGallery disabled={busy} onPhoto={(file) => void capture(file)} />
        {photo && <img className="max-h-48 rounded-xl" src={`data:image/jpeg;base64,${photo}`} alt="Vista previa de nueva fachada" />}
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={busy || !photo || !version} onClick={() => void confirm()}>Confirmar reemplazo</Button>
          <Button type="button" variant="secondary" disabled={busy} onClick={() => { setEditing(false); setPhoto(''); setError('') }}>Cancelar</Button>
        </div>
      </> : version && <Button type="button" variant="secondary" onClick={() => setEditing(true)}>Cambiar foto de fachada</Button>}
    </div>
  )
}
