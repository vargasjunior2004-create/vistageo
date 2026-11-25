import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiRequest, clearTokens, getAccessToken, getRefreshToken, setTokens } from '../api/client'
import type { SessionUser } from '../types/api'

type AuthState = {
  user: SessionUser | null
  permissions: string[]
  loading: boolean
  error: string | null
  passwordChanged: boolean
  sessionExpired: boolean
  login: (username: string, password: string) => Promise<SessionUser>
  logout: () => Promise<void>
  clearSession: (passwordChanged?: boolean) => void
  refresh: () => Promise<void>
  hasPermission: (permission: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

function enableLocalJornada(user: SessionUser) {
  if (!user.must_change_password && ['ADMINISTRADOR', 'GERENCIA', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user.role_name)) {
    localStorage.setItem('vistageo_jornada_habilitada', 'true')
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [passwordChanged, setPasswordChanged] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)

  const clearSession = useCallback((changed = false) => {
    clearTokens()
    setUser(null)
    setError(null)
    setPasswordChanged(changed)
    setSessionExpired(false)
  }, [])

  useEffect(() => {
    const expire = () => {
      clearSession()
      setSessionExpired(true)
    }
    window.addEventListener('vistageo:session-expired', expire)
    return () => window.removeEventListener('vistageo:session-expired', expire)
  }, [clearSession])

  const refresh = useCallback(async () => {
    setError(null)
    const hasRefresh = !!getRefreshToken()
    const hasAccess = !!getAccessToken()
    if (!hasRefresh && !hasAccess) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      if (hasRefresh && !hasAccess) {
        const refreshed = await apiRequest<{ access_token: string; refresh_token?: string }>('/auth/refresh', {
          method: 'POST',
          body: { refresh_token: getRefreshToken() },
          activity: false,
        })
        setTokens(refreshed.access_token, refreshed.refresh_token ?? getRefreshToken())
      }
      const me = await apiRequest<SessionUser>('/auth/me')
      enableLocalJornada(me)
      setUser(me)
    } catch (err) {
      setUser(null)
      if (err instanceof Error && 'status' in err && (err as { status?: number }).status === 401) {
        clearTokens()
        setSessionExpired(true)
      } else {
        setError(err instanceof Error ? err.message : 'No se pudo verificar la sesión')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    const result = await apiRequest<{ access_token: string; refresh_token?: string; must_change_password: boolean }>('/auth/login', {
      method: 'POST',
      body: { username: username.toUpperCase(), password },
      activity: false,
    })
    setTokens(result.access_token, result.refresh_token ?? null)
    const me = await apiRequest<SessionUser>('/auth/me')
    enableLocalJornada(me)
    setUser(me)
    setError(null)
    setPasswordChanged(false)
    setSessionExpired(false)
    return me
  }, [])

  const logout = useCallback(async () => {
    try {
      await apiRequest('/auth/logout', { method: 'POST' })
    } finally {
      clearSession()
    }
  }, [clearSession])

  const permissions = useMemo(() => user?.permissions ?? [], [user])

  const hasPermission = useCallback(
    (permission: string) => {
      if (!user) return false
      if (user.role_name === 'ADMINISTRADOR') return true
      return permissions.includes(permission)
    },
    [user, permissions],
  )

  const value = useMemo<AuthState>(
    () => ({ user, permissions, loading, error, passwordChanged, sessionExpired, login, logout, clearSession, refresh, hasPermission }),
    [user, permissions, loading, error, passwordChanged, sessionExpired, login, logout, clearSession, refresh, hasPermission],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
