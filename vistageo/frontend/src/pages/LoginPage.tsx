import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await login(username, password)
      navigate(user.must_change_password ? '/cambiar-contrasena' : '/')
    } catch (err) {
      setError((err as Error).message || 'Credenciales inválidas')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 to-teal-700 text-xl font-bold text-white shadow-xl shadow-teal-600/30">
            VG
          </span>
          <h1 className="mt-4 text-3xl font-bold tracking-tight text-slate-900">VISTA GEO</h1>
          <p className="mt-1 text-sm text-slate-500">Acceso al panel técnico</p>
        </div>
        <form onSubmit={submit} className="space-y-5 rounded-3xl bg-white p-7 shadow-xl shadow-slate-200/60 ring-1 ring-slate-100">
          <Input
            label="Usuario"
            value={username}
            onChange={(e) => setUsername(e.target.value.toUpperCase())}
            autoComplete="username"
            placeholder="Usuario"
            required
          />
          {location.state?.passwordChanged && <p className="text-sm text-teal-700">Contraseña actualizada. Inicia sesión nuevamente.</p>}
          {location.state?.sessionExpired && <p className="text-sm text-rose-600">La sesión venció o fue revocada. Inicia sesión nuevamente.</p>}
          <Input
            label="Contraseña"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value.toUpperCase())}
            autoComplete="current-password"
            placeholder="••••••••"
            required
          />
          {error && (
            <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm font-medium text-rose-600 ring-1 ring-rose-100">
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Ingresando...' : 'Ingresar'}
          </Button>
        </form>
        <p className="mt-6 text-center text-xs text-slate-400">
          Las credenciales se convierten a mayúsculas automáticamente.
        </p>
        {localStorage.getItem('vistageo_jornada_habilitada') === 'true' && (
          <p className="mt-4 text-center text-sm"><Link className="font-semibold text-blue-700" to="/jornada/camara">Abrir fotos de jornada en este dispositivo</Link></p>
        )}
      </div>
    </div>
  )
}
