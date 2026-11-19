import { useRef } from 'react'
import { Button } from './Button'

export function CameraInput({ onPhoto, disabled = false }: { onPhoto: (file: File) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onPhoto(file)
          event.target.value = ''
        }}
      />
      <Button type="button" disabled={disabled} onClick={() => input.current?.click()}>Abrir cámara</Button>
    </>
  )
}
