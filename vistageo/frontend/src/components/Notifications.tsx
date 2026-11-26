import { Toaster } from 'sonner'

export function Notifications() {
  return <Toaster
    position="top-right"
    duration={6000}
    closeButton
    richColors
    expand={false}
    toastOptions={{ closeButtonAriaLabel: 'Cerrar notificación' }}
    containerAriaLabel="Notificaciones"
  />
}
