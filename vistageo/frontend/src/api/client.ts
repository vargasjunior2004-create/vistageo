const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

const ACCESS_TOKEN_KEY = 'vistageo_token'
const REFRESH_TOKEN_KEY = 'vistageo_refresh_token'

let accessToken: string | null = null
let refreshPromise: Promise<string | null> | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function getToken(): string | null {
  return getAccessToken()
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setTokens(access: string, refresh?: string | null): void {
  accessToken = access
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
}

export function setToken(token: string): void {
  setTokens(token, getRefreshToken())
}

export function clearTokens(): void {
  accessToken = null
  refreshPromise = null
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function clearToken(): void {
  clearTokens()
}

function migrateLegacyToken(): void {
  if (accessToken || getRefreshToken()) return
  const legacy = localStorage.getItem(ACCESS_TOKEN_KEY)
  if (legacy) {
    accessToken = legacy
    localStorage.removeItem(ACCESS_TOKEN_KEY)
  }
}

export type RequestOptions = {
  method?: string
  body?: unknown
  activity?: boolean
  signal?: AbortSignal
  _retried?: boolean
}

async function readError(response: Response): Promise<Error & { status?: number; data?: unknown }> {
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
  return err
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise
  const refreshToken = getRefreshToken()
  if (!refreshToken) return null
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: 'POST',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (!response.ok) {
        clearTokens()
        return null
      }
      const data = await response.json() as { access_token: string; refresh_token?: string }
      setTokens(data.access_token, data.refresh_token ?? refreshToken)
      return data.access_token
    } catch {
      clearTokens()
      return null
    } finally {
      refreshPromise = null
    }
  })()
  return refreshPromise
}

async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  migrateLegacyToken()
  const { method = 'GET', body, activity = method !== 'GET', signal, _retried = false } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getAccessToken()
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
    if (
      response.status === 401 &&
      token &&
      !_retried &&
      path !== '/auth/login' &&
      path !== '/auth/refresh'
    ) {
      const newToken = await refreshAccessToken()
      if (newToken) {
        return apiFetch(path, { ...options, _retried: true })
      }
      if (getAccessToken() === null && getRefreshToken() === null) {
        window.dispatchEvent(new Event('vistageo:session-expired'))
      }
    }
    throw await readError(response)
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
