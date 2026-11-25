type CameraDiagnosticDetails = Partial<{
  source: 'camera' | 'gallery'
  fileSize: number
  mimeType: string
  width: number
  height: number
  outputBytes: number
  errorName: string
  visible: boolean
  persisted: boolean
}>

type CameraDiagnosticEvent = {
  at: string
  attempt: number
  event: string
  details: CameraDiagnosticDetails
}

type CameraDiagnosticState = {
  attempt: number
  events: CameraDiagnosticEvent[]
}

const storageKey = 'vistageo_camera_diagnostics'
const maxEvents = 100

function readState(): CameraDiagnosticState {
  try {
    const stored = window.localStorage.getItem(storageKey)
    if (!stored) return { attempt: 0, events: [] }
    const value: unknown = JSON.parse(stored)
    if (typeof value !== 'object' || value === null) throw new Error('Invalid diagnostic state')
    const state = value as Partial<CameraDiagnosticState>
    if (!Number.isSafeInteger(state.attempt) || !Array.isArray(state.events)) {
      throw new Error('Invalid diagnostic state')
    }
    return { attempt: state.attempt!, events: state.events.slice(-maxEvents) }
  } catch (error) {
    console.warn('[GeoVista camera] No se pudieron leer los diagnósticos locales.', error)
    return { attempt: 0, events: [] }
  }
}

function writeState(state: CameraDiagnosticState): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(state))
  } catch (error) {
    console.warn('[GeoVista camera] No se pudieron guardar los diagnósticos locales.', error)
  }
}

export function recordCameraEvent(event: string, details: CameraDiagnosticDetails = {}): void {
  const state = readState()
  const entry: CameraDiagnosticEvent = {
    at: new Date().toISOString(),
    attempt: state.attempt,
    event,
    details,
  }
  state.events.push(entry)
  state.events = state.events.slice(-maxEvents)
  writeState(state)
  console.info('[GeoVista camera]', entry)
}

export function beginCameraAttempt(source: 'camera' | 'gallery'): number {
  const state = readState()
  state.attempt += 1
  writeState(state)
  recordCameraEvent('selection_requested', { source })
  return state.attempt
}
