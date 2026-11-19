const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

const TOKEN_KEY = 'vistageo_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export type RequestOptions = {
  method?: string
  body?: unknown
  activity?: boolean
  signal?: AbortSignal
}

async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  const { method = 'GET', body, activity = method !== 'GET', signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (activity && token) headers['X-Actividad-Usuario'] = 'true'
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  })

  if (!response.ok) {
    if (response.status === 401 && token && getToken() === token && path !== '/auth/login') {
      window.dispatchEvent(new Event('vistageo:session-expired'))
    }
    const text = await response.text()
    let data: unknown = null
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
    let message = `Error ${response.status}`
    if (data && typeof data === 'object' && 'detail' in data) {
      message = String((data as { detail: unknown }).detail)
    }
    const err = new Error(message) as Error & { status?: number; data?: unknown }
    err.status = response.status
    err.data = data
    throw err
  }
  return response
}

export async function apiRequest<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await apiFetch(path, options)
  if (response.status === 204) return undefined as T
  return await response.json() as T
}

export async function apiPhoto(path: string, signal?: AbortSignal): Promise<{ blob: Blob; version: string | null }> {
  const response = await apiFetch(path, { signal })
  return { blob: await response.blob(), version: response.headers.get('X-Foto-Version') }
}
