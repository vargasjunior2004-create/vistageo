import { useRef } from 'react'
import { Button } from './Button'

export function CameraInput({ onPhoto, disabled = false, allowGallery = false }: { onPhoto: (file: File) => void; disabled?: boolean; allowGallery?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const gallery = useRef<HTMLInputElement>(null)
  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) onPhoto(file)
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
        onChange={handleChange}
      />
      {allowGallery && <input ref={gallery} type="file" accept="image/*" className="sr-only" onChange={handleChange} />}
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={disabled} onClick={() => input.current?.click()}>Abrir cámara</Button>
        {allowGallery && <Button type="button" variant="secondary" disabled={disabled} onClick={() => gallery.current?.click()}>Elegir imagen</Button>}
      </div>
    </>
  )
}
