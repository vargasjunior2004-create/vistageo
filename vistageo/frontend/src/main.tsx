import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { Notifications } from './components/Notifications'
import { recordCameraEvent } from './services/cameraDiagnostics'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    <Notifications />
  </StrictMode>,
)

document.addEventListener('visibilitychange', () => {
  recordCameraEvent('document_visibility_changed', { visible: document.visibilityState === 'visible' })
})
window.addEventListener('pagehide', (event) => {
  recordCameraEvent('page_hidden', { persisted: event.persisted })
})
window.addEventListener('pageshow', (event) => {
  recordCameraEvent('page_shown', { persisted: event.persisted })
})
window.addEventListener('error', (event) => {
  recordCameraEvent('javascript_error', { errorName: event.error instanceof Error ? event.error.name : 'Error' })
})
window.addEventListener('unhandledrejection', (event) => {
  recordCameraEvent('unhandled_rejection', {
    errorName: event.reason instanceof Error ? event.reason.name : 'UnknownError',
  })
})

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch((error: unknown) => {
      console.error('No se pudo activar el modo sin conexión:', error)
    })
  })
}
