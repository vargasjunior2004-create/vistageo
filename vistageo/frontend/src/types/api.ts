export type UserRead = {
  id: number
  username: string
  active: boolean
  role_id: number
  must_change_password: boolean
}

export type SessionUser = UserRead & {
  role_name: string
  permissions: string[]
}

export type Role = {
  id: number
  name: string
  permissions: string[]
}

export type Contract = { kardex: string }

export type Location = {
  id: number
  kardex: string
  revision_actual_id: number | null
  creado_en: string | null
  creado_por_nombre: string | null
  registro_pendiente: boolean | null
  latitud: string | null
  longitud: string | null
  url_gps: string | null
  metodo_coordenadas: 'GPS_DISPOSITIVO' | 'ENLACE_COMPARTIDO' | null
  precision_metros: number | null
  capturado_en: string | null
  capturado_por: number | null
  version: number
}

export type UpdateReason = { id: number; nombre: string; activo: boolean }
export type LocationUpdateAudit = {
  id: number
  usuario: string
  fecha: string
  kardex: string
  motivo: string
  observacion: string | null
  fachada: boolean
  gps: boolean
  latitud: string | null
  longitud: string | null
  precision_metros: number | null
  capturado_en: string | null
  metodo_coordenadas: 'GPS_DISPOSITIVO' | null
}

export type LocationRevision = {
  id: number
  ubicacion_id: number
  url_gps: string | null
  metodo_coordenadas: 'GPS_DISPOSITIVO' | 'ENLACE_COMPARTIDO' | null
  latitud: string | null
  longitud: string | null
  fecha_evento: string | null
  precision_metros: number | null
  registrado_en: string
  responsable_id: number | null
  cerrada: boolean
}

export type HistoricalSource = {
  id: number
  ruta_original: string
  tipo: string
  sha256: string | null
  estado_revision: string
  kardex: string | null
}

export type ApiError = { detail?: string; fields?: unknown }
