export type GpsLimits = { excelente: number; buena: number; aceptable: number; baja: number }
export type GpsPosition = { latitude: number; longitude: number; accuracy: number; capturedAt: string; acceptable: boolean }

export function gpsQuality(accuracy: number, limits: GpsLimits): string {
  if (accuracy <= limits.excelente) return 'Excelente'
  if (accuracy <= limits.buena) return 'Buena'
  if (accuracy <= limits.aceptable) return 'Aceptable'
  if (accuracy <= limits.baja) return 'Baja'
  return 'Deficiente'
}

export function isGpsPositionValid(position: GeolocationPosition, startedAt: number, now: number): boolean {
  const { latitude, longitude, accuracy } = position.coords
  return Number.isFinite(latitude) && Math.abs(latitude) <= 90
    && Number.isFinite(longitude) && Math.abs(longitude) <= 180
    && Number.isFinite(accuracy) && accuracy >= 0
    && Number.isFinite(position.timestamp) && position.timestamp >= startedAt - 1000 && position.timestamp <= now + 5000
}
