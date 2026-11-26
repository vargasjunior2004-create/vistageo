import { useEffect, useState } from 'react'
import { apiPhoto } from '../api/client'
import { SkeletonImage } from './Skeleton'

export function LocationPhoto({ locationId, thumbnail = false, onVersion }: { locationId: number; thumbnail?: boolean; onVersion?: (version: string | null) => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('Cargando fotografía...')

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null
    setUrl(null)
    setLoading(true)
    setMessage('Cargando fotografía...')
    apiPhoto(`/ubicaciones/${locationId}/fotografia`, controller.signal)
      .then(({ blob, version }) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
        onVersion?.(version)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof Error && 'status' in err && err.status === 404) {
          setMessage('Esta ubicación no tiene fotografía.')
        } else {
          setMessage(err instanceof Error ? err.message : 'No se pudo cargar la fotografía.')
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [locationId, onVersion])

  return url
    ? <img src={url} alt="Fachada del contrato seleccionado" className={thumbnail ? 'h-20 w-20 rounded-xl object-cover' : 'max-h-96 rounded-xl object-contain'} />
    : loading
      ? <SkeletonImage className={thumbnail ? 'h-20 w-20 rounded-xl' : 'h-64 max-h-96 max-w-2xl rounded-xl'} aspectRatio={thumbnail ? '1 / 1' : '4 / 3'} />
      : <span className={thumbnail ? 'block w-20 text-xs text-slate-500' : 'block text-sm text-slate-500'}>{message}</span>
}
