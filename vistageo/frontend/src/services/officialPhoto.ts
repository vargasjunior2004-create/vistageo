import { recordCameraEvent } from './cameraDiagnostics'

export async function encodeOfficialPhoto(file: File): Promise<string> {
  if (!file.type.startsWith('image/') || file.size > 25 * 1024 * 1024) {
    recordCameraEvent('photo_rejected', { fileSize: file.size, mimeType: file.type || 'unknown' })
    throw new Error('Selecciona una imagen de hasta 25 MB.')
  }
  recordCameraEvent('photo_processing_started', { fileSize: file.size, mimeType: file.type || 'unknown' })
  let bitmap: ImageBitmap | undefined
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('No se pudo preparar la fotografía.')
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const photo = canvas.toDataURL('image/jpeg', 0.86).split(',')[1]
    const padding = photo.endsWith('==') ? 2 : photo.endsWith('=') ? 1 : 0
    recordCameraEvent('photo_processing_completed', {
      width: canvas.width,
      height: canvas.height,
      outputBytes: Math.floor(photo.length * 3 / 4) - padding,
    })
    return photo
  } catch (error) {
    recordCameraEvent('photo_processing_failed', {
      errorName: error instanceof Error ? error.name : 'UnknownError',
      ...(bitmap ? { width: bitmap.width, height: bitmap.height } : {}),
    })
    throw error
  } finally {
    bitmap?.close()
  }
}
