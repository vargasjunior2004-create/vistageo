import { useEffect, useState } from 'react'
import { apiPhoto } from '../api/client'

export function LocationPhoto({ locationId, thumbnail = false }: { locationId: number; thumbnail?: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [message, setMessage] = useState('Cargando fotografía...')

  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | null = null
    setUrl(null)
    setMessage('Cargando fotografía...')
    apiPhoto(`/ubicaciones/${locationId}/fotografia`, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (err instanceof Error && 'status' in err && err.status === 404) {
          setMessage('Esta ubicación no tiene fotografía.')
        } else {
          setMessage(err instanceof Error ? err.message : 'No se pudo cargar la fotografía.')
        }
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [locationId])

  return url
    ? <img src={url} alt="Fachada del contrato seleccionado" className={thumbnail ? 'h-20 w-20 rounded-xl object-cover' : 'max-h-96 rounded-xl object-contain'} />
    : <span className={thumbnail ? 'block w-20 text-xs text-slate-500' : 'block text-sm text-slate-500'}>{message}</span>
}
