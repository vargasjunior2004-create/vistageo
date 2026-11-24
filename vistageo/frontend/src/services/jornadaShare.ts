import type { JornadaPhoto } from './localPhotos'

export function prepareJornadaShare(
  photos: JornadaPhoto[], selected: string[], descriptions: Record<string, string>,
): { photos: JornadaPhoto[]; text?: string } {
  const selectedPhotos = photos.filter((photo) => selected.includes(photo.id))
  if (!selectedPhotos.some((photo) => descriptions[photo.id])) return { photos: selectedPhotos }

  const text = selectedPhotos.map((photo, index) => {
    const description = descriptions[photo.id] ?? ''
    return `Foto ${index + 1}:${description ? ` ${description}` : ''}`
  }).join('\n')
  return { photos: selectedPhotos, text }
}
