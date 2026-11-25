import { useRef } from 'react'
import { beginCameraAttempt, recordCameraEvent } from '../services/cameraDiagnostics'
import { Button } from './Button'

export function CameraInput({ onPhoto, disabled = false, allowGallery = false }: { onPhoto: (file: File) => void; disabled?: boolean; allowGallery?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const gallery = useRef<HTMLInputElement>(null)
  const handleChange = (event: React.ChangeEvent<HTMLInputElement>, source: 'camera' | 'gallery') => {
    const file = event.target.files?.[0]
    if (file) {
      recordCameraEvent('selection_received', { source, fileSize: file.size, mimeType: file.type || 'unknown' })
      onPhoto(file)
    } else {
      recordCameraEvent('selection_empty', { source })
    }
    event.target.value = ''
  }
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        onClick={() => { beginCameraAttempt('camera') }}
        onChange={(event) => handleChange(event, 'camera')}
      />
      {allowGallery && <input
        ref={gallery}
        type="file"
        accept="image/*"
        className="sr-only"
        onClick={() => { beginCameraAttempt('gallery') }}
        onChange={(event) => handleChange(event, 'gallery')}
      />}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={disabled} onClick={() => input.current?.click()}>Abrir cámara</Button>
        {allowGallery && <Button type="button" variant="secondary" disabled={disabled} onClick={() => gallery.current?.click()}>Elegir imagen</Button>}
      </div>
    </>
  )
}
