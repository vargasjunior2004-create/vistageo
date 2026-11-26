import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { CameraInput } from '../components/CameraInput'
import { SkeletonImage } from '../components/Skeleton'
import { notifications } from '../services/notifications'
import { deletePhotos, listPhotos, savePhoto, type JornadaPhoto } from '../services/localPhotos'
import { prepareJornadaShare } from '../services/jornadaShare'

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
  const [descriptions, setDescriptions] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<JornadaPhoto | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingPhotos, setLoadingPhotos] = useState(true)
  const [photosLoaded, setPhotosLoaded] = useState(false)

  const load = async () => {
    const saved = await listPhotos()
    setPhotos(saved.sort((a, b) => b.createdAt - a.createdAt))
    setPhotosLoaded(true)
  }

  useEffect(() => {
    let active = true
    listPhotos().then((items) => {
      if (active) {
        setPhotos(items.sort((a, b) => b.createdAt - a.createdAt))
        setPhotosLoaded(true)
      }
    }).catch(() => {
      if (active) notifications.error('No se pudieron cargar las fotos. Inténtalo nuevamente.')
    }).finally(() => { if (active) setLoadingPhotos(false) })
    return () => { active = false }
  }, [])

  const capture = async (file: File) => {
    setBusy(true)
    try {
      if (!file.type.startsWith('image/') || !file.size) {
        notifications.warning('El archivo seleccionado no es una imagen válida.')
        return
      }
      const image = await createImageBitmap(file)
      image.close()
      await savePhoto(file)
      notifications.success('Foto guardada en este dispositivo.')
      try {
        await load()
      } catch {
        notifications.error('La foto se guardó, pero no se pudo actualizar la galería.')
      }
      if (navigator.storage?.persist) {
        try {
          if (!(await navigator.storage.persist())) notifications.warning('El navegador no garantizó almacenamiento persistente; no borres los datos del sitio.')
        } catch {
          notifications.warning('No se pudo comprobar el almacenamiento persistente. No borres los datos del sitio.')
        }
      }
    } catch {
      notifications.error('No se pudo guardar la foto. Inténtalo nuevamente.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!selected.length || !window.confirm(`¿Eliminar ${selected.length} foto(s) de este dispositivo?`)) return
    try {
      await deletePhotos(selected)
      setPhotos((current) => current.filter((photo) => !selected.includes(photo.id)))
      setDescriptions((current) => Object.fromEntries(
        Object.entries(current).filter(([id]) => !selected.includes(id)),
      ))
      setSelected([])
      setPreview(null)
      notifications.success('Fotos eliminadas de este dispositivo.')
      try {
        await load()
      } catch {
        setPhotosLoaded(false)
        notifications.error('Las fotos se eliminaron, pero no se pudo actualizar la galería.')
      }
    } catch {
      notifications.error('No se pudieron eliminar las fotos. Inténtalo nuevamente.')
    }
  }

  const share = async () => {
    try {
      const extensions: Record<string, string> = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/heic': 'heic' }
      const prepared = prepareJornadaShare(photos, selected, descriptions)
      const files = prepared.photos
        .map((photo) => new File([photo.blob], `jornada-${photo.id}.${extensions[photo.blob.type] ?? 'img'}`,
          { type: photo.blob.type || 'image/jpeg', lastModified: photo.createdAt }))
      if (!files.length) {
        notifications.warning('Selecciona al menos una foto.')
        return
      }
      if (!navigator.share || !navigator.canShare?.({ files })) {
        notifications.warning('Este navegador no permite compartir estas fotos. Usa un dispositivo compatible.')
        return
      }
      await navigator.share({ files, title: 'Fotos de jornada', ...(prepared.text === undefined ? {} : { text: prepared.text }) })
      notifications.info('Se abrió el selector para compartir. Confirma el envío en WhatsApp.')
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        notifications.info('No se compartieron las fotos.')
      } else {
        notifications.error('No se pudieron preparar o compartir las fotos. Inténtalo nuevamente.')
      }
    }
  }

  const selectedPhotos = photos.filter((photo) => selected.includes(photo.id))

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="space-y-1">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-action-strong">Jornada local</p>
        <h1 className="page-title">{mode === 'camera' ? 'Sacar fotos' : 'Mis fotos'}</h1>
        <p className="page-description">Estas fotos permanecen en este dispositivo y no se suben al servidor.</p>
      </header>
      <div className="flex flex-wrap gap-3 text-sm font-semibold text-primary">
        <Link to="/">Inicio</Link>
        <Link to="/jornada/camara">Sacar fotos</Link>
        <Link to="/jornada/fotos">Mis fotos ({photos.length})</Link>
      </div>
      <p className="text-sm text-slate-600">Cualquier persona con acceso a este navegador puede ver las fotos locales. No borres los datos del sitio.</p>
      {loadingPhotos && !photosLoaded && <div role="status" aria-label="Cargando fotos" className="sr-only">Cargando fotos...</div>}
      {!loadingPhotos && !photosLoaded && <Button type="button" variant="secondary" onClick={() => {
        setLoadingPhotos(true)
        void load().catch(() => notifications.error('No se pudieron cargar las fotos. Inténtalo nuevamente.'))
          .finally(() => setLoadingPhotos(false))
      }}>Reintentar carga de fotos</Button>}
      {mode === 'camera' ? (
        <div className="surface-panel space-y-4 p-5">
          <p>Abre la cámara y guarda las fotos de tu jornada. Puedes repetir la captura.</p>
          <CameraInput disabled={busy} onPhoto={(file) => void capture(file)} />
          {loadingPhotos && !photosLoaded
            ? <div role="status" aria-label="Cargando fotografía reciente"><SkeletonImage className="h-52 rounded-xl" aspectRatio="4 / 3" /></div>
            : photos[0] && <div className="h-52 overflow-hidden rounded-xl"><PhotoThumbnail photo={photos[0]} /></div>}
          <p><Link className="font-semibold text-action-strong" to="/jornada/fotos">Ver mis fotos →</Link></p>
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
          {!!selected.length && <p className="text-sm text-slate-600">Las descripciones son opcionales y se incluyen en un reporte numerado. Su recepción depende de la aplicación y del dispositivo.</p>}
          {photosLoaded && !photos.length && <p className="empty-state">Todavía no hay fotos. Abre la cámara para empezar.</p>}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {loadingPhotos && !photosLoaded
              ? Array.from({ length: 8 }, (_, index) => <SkeletonImage key={index} className="h-36 rounded-xl border border-slate-200" aspectRatio="1 / 1" />)
              : photos.map((photo) => (
              <div key={photo.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <button type="button" onClick={() => setPreview(photo)} className="block h-36 w-full" aria-label="Ampliar foto">
                  <PhotoThumbnail photo={photo} />
                </button>
                <label className="flex items-center gap-2 p-3 text-xs">
                  <input type="checkbox" checked={selected.includes(photo.id)} onChange={(event) => {
                    setSelected(event.target.checked ? [...selected, photo.id] : selected.filter((id) => id !== photo.id))
                  }} />
                  {new Date(photo.createdAt).toLocaleString()}
                </label>
                {selected.includes(photo.id) && <label className="block px-3 pb-3 text-xs font-medium text-slate-700">
                  Descripción opcional · Foto {selectedPhotos.findIndex((item) => item.id === photo.id) + 1}
                  <textarea
                    className="mt-1 block w-full rounded-lg border border-border bg-surface px-2 py-2 text-sm text-text-primary focus:border-action focus:outline-none focus:ring-2 focus:ring-action/15"
                    rows={2}
                    value={descriptions[photo.id] ?? ''}
                    onChange={(event) => setDescriptions((current) => ({ ...current, [photo.id]: event.target.value }))}
                  />
                </label>}
              </div>
            ))}
          </div>
          {preview && <div role="dialog" aria-modal="true" aria-label="Vista de fotografía" className="photo-preview-overlay fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="photo-preview-dialog space-y-3 p-3">
              <div className="h-[60vh] overflow-hidden rounded-xl"><PhotoThumbnail photo={preview} contain /></div>
              <Button type="button" onClick={() => setPreview(null)}>Cerrar</Button>
            </div>
          </div>}
        </>
      )}
    </div>
  )
}
