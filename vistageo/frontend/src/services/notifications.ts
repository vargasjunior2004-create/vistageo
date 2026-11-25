import { toast } from 'sonner'

type NotificationType = 'success' | 'error' | 'warning' | 'info'

function notify(type: NotificationType, message: string, key?: string) {
  toast[type](message, { id: key ?? JSON.stringify([type, message]) })
}

export const notifications = {
  success: (message: string, key?: string) => notify('success', message, key),
  error: (message: string, key?: string) => notify('error', message, key),
  warning: (message: string, key?: string) => notify('warning', message, key),
  info: (message: string, key?: string) => notify('info', message, key),
  dismiss: (key: string) => { toast.dismiss(key) },
}
