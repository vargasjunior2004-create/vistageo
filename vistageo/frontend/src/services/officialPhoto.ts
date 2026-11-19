export async function encodeOfficialPhoto(file: File): Promise<string> {
  if (!file.type.startsWith('image/') || file.size > 25 * 1024 * 1024) {
    throw new Error('Selecciona una imagen de hasta 25 MB.')
  }
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('No se pudo preparar la fotografía.')
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.86).split(',')[1]
  } finally {
    bitmap.close()
  }
}
