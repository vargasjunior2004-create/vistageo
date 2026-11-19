import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiRequest, clearToken, getToken, setToken } from '../api/client'
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
  if (!user.must_change_password && ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user.role_name)) {
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
    clearToken()
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
    const token = getToken()
    setError(null)
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await apiRequest<SessionUser>('/auth/me')
      enableLocalJornada(me)
      setUser(me)
    } catch (err) {
      setUser(null)
      if (err instanceof Error && 'status' in err && err.status === 401) {
        if (getToken() === token) clearSession()
      } else {
        setError(err instanceof Error ? err.message : 'No se pudo verificar la sesión')
      }
    } finally {
      setLoading(false)
    }
  }, [clearSession])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (username: string, password: string) => {
    const result = await apiRequest<{ access_token: string; must_change_password: boolean }>('/auth/login', {
      method: 'POST',
      body: { username: username.toUpperCase(), password },
      activity: false,
    })
    setToken(result.access_token)
    const me = await apiRequest<SessionUser>('/auth/me')
    enableLocalJornada(me)
    setUser(me)
    setError(null)
    setPasswordChanged(false)
    setSessionExpired(false)
    return me
  }, [])

  const logout = useCallback(async () => {
    await apiRequest('/auth/logout', { method: 'POST' })
    clearSession()
  }, [clearSession])

  const permissions = useMemo(() => {
    return user?.permissions ?? []
  }, [user])

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
