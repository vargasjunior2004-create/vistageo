import { useEffect, useState } from 'react'
import { apiPhoto } from '../api/client'

export function LocationPhoto({ locationId }: { locationId: number }) {
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
    ? <img src={url} alt="Fachada del contrato seleccionado" className="max-h-96 rounded-xl object-contain" />
    : <p className="text-sm text-slate-500">{message}</p>
}
