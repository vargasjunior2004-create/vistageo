import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { CameraInput } from '../components/CameraInput'
import { deletePhotos, listPhotos, savePhoto, type JornadaPhoto } from '../services/localPhotos'

function PhotoThumbnail({ photo, contain = false }: { photo: JornadaPhoto; contain?: boolean }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const objectUrl = URL.createObjectURL(photo.blob)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [photo.blob])
  return url ? <img src={url} alt="Fotografía de jornada" className={`h-full w-full ${contain ? 'object-contain' : 'object-cover'}`} /> : null
}

export function JornadaPage({ mode }: { mode: 'camera' | 'gallery' }) {
  const [photos, setPhotos] = useState<JornadaPhoto[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [preview, setPreview] = useState<JornadaPhoto | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    const saved = await listPhotos()
    setPhotos(saved.sort((a, b) => b.createdAt - a.createdAt))
  }

  useEffect(() => {
    listPhotos().then((items) => setPhotos(items.sort((a, b) => b.createdAt - a.createdAt)))
      .catch((err: Error) => setMessage(err.message))
  }, [])

  const capture = async (file: File) => {
    setBusy(true)
    setMessage('')
    try {
      if (!file.type.startsWith('image/') || !file.size) throw new Error('El archivo seleccionado no es una imagen válida.')
      const image = await createImageBitmap(file)
      image.close()
      await savePhoto(file)
      await load()
      setMessage('Foto guardada en este dispositivo.')
      if (navigator.storage?.persist) {
        try {
          if (!(await navigator.storage.persist())) setMessage('Foto guardada. El navegador no garantizó almacenamiento persistente; no borres los datos del sitio.')
        } catch {
          setMessage('Foto guardada. No se pudo comprobar el almacenamiento persistente.')
        }
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'No se pudo guardar la foto.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selected.length || !window.confirm(`¿Eliminar ${selected.length} foto(s) de este dispositivo?`)) return
    try {
      await deletePhotos(selected)
      setSelected([])
      setPreview(null)
      await load()
      setMessage('Fotos eliminadas de este dispositivo.')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'No se pudieron eliminar las fotos.')
    }
  }

  const share = async () => {
    const extensions: Record<string, string> = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/heic': 'heic' }
    const files = photos.filter((photo) => selected.includes(photo.id))
      .map((photo) => new File([photo.blob], `jornada-${photo.id}.${extensions[photo.blob.type] ?? 'img'}`,
        { type: photo.blob.type || 'image/jpeg', lastModified: photo.createdAt }))
    if (!files.length) {
      setMessage('Selecciona al menos una foto.')
      return
    }
    if (!navigator.share || !navigator.canShare?.({ files })) {
      setMessage('Este navegador no permite compartir estas fotos. Usa un dispositivo compatible.')
      return
    }
    try {
      await navigator.share({ files, title: 'Fotos de jornada' })
      setMessage('Se abrió el selector para compartir. Confirma el envío en WhatsApp.')
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setMessage('No se compartieron las fotos.')
      } else {
        setMessage('No se pudo abrir el selector para compartir.')
      }
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-6">
      <header className="rounded-3xl bg-[#102c50] p-5 text-white">
        <p className="text-sm text-blue-200">VISTA GEO · Jornada local</p>
        <h1 className="mt-1 text-2xl font-bold">{mode === 'camera' ? 'Sacar fotos' : 'Mis fotos'}</h1>
        <p className="mt-2 text-sm text-blue-100">Estas fotos permanecen en este dispositivo y no se suben al servidor.</p>
      </header>
      <div className="flex flex-wrap gap-3 text-sm font-semibold text-blue-800">
        <Link to="/">Inicio</Link>
        <Link to="/jornada/camara">Sacar fotos</Link>
        <Link to="/jornada/fotos">Mis fotos ({photos.length})</Link>
      </div>
      <p className="text-sm text-slate-600">Cualquier persona con acceso a este navegador puede ver las fotos locales. No borres los datos del sitio.</p>
      {message && <p role="status" className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900">{message}</p>}
      {mode === 'camera' ? (
        <div className="space-y-4 rounded-3xl bg-white p-6 shadow-sm">
          <p>Abre la cámara y guarda las fotos de tu jornada. Puedes repetir la captura.</p>
          <CameraInput disabled={busy} onPhoto={(file) => void capture(file)} />
          {photos[0] && <div className="h-52 overflow-hidden rounded-xl"><PhotoThumbnail photo={photos[0]} /></div>}
          <p><Link className="font-semibold text-blue-700" to="/jornada/fotos">Ver mis fotos →</Link></p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" disabled={!photos.length} onClick={() => setSelected(selected.length === photos.length ? [] : photos.map((photo) => photo.id))}>
              {selected.length === photos.length && photos.length ? 'Deseleccionar todas' : 'Seleccionar todas'}
            </Button>
            <Button type="button" variant="danger" disabled={!selected.length} onClick={() => void remove()}>Eliminar ({selected.length})</Button>
            <Button type="button" disabled={!selected.length} onClick={() => void share()}>Compartir fotos</Button>
          </div>
          {!photos.length && <p className="rounded-2xl bg-white p-5 text-slate-600">Todavía no hay fotos. Abre la cámara para empezar.</p>}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {photos.map((photo) => (
              <div key={photo.id} className="overflow-hidden rounded-2xl bg-white shadow-sm">
                <button type="button" onClick={() => setPreview(photo)} className="block h-36 w-full" aria-label="Ampliar foto">
                  <PhotoThumbnail photo={photo} />
                </button>
                <label className="flex items-center gap-2 p-3 text-xs">
                  <input type="checkbox" checked={selected.includes(photo.id)} onChange={(event) => {
                    setSelected(event.target.checked ? [...selected, photo.id] : selected.filter((id) => id !== photo.id))
                  }} />
                  {new Date(photo.createdAt).toLocaleString()}
                </label>
              </div>
            ))}
          </div>
          {preview && <div role="dialog" aria-modal="true" aria-label="Vista de fotografía" className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-4">
            <div className="w-full max-w-2xl space-y-3 rounded-2xl bg-white p-3">
              <div className="h-[60vh] overflow-hidden rounded-xl"><PhotoThumbnail photo={preview} contain /></div>
              <Button type="button" onClick={() => setPreview(null)}>Cerrar</Button>
            </div>
          </div>}
        </>
      )}
    </div>
  )
}
