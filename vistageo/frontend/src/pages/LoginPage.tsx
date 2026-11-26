import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Icon } from '../components/Icon'
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
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-7 text-center">
          <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-white shadow-sm">
            <Icon name="locations" className="h-6 w-6" />
          </span>
          <h1 className="mt-4 text-2xl font-bold tracking-[0.05em] text-primary">VISTA GEO</h1>
          <p className="mt-1 text-sm text-slate-500">Accede a las ubicaciones de tus clientes</p>
        </div>
        <form onSubmit={submit} className="surface-panel space-y-5 p-5 sm:p-7">
          <Input
            label="Usuario"
            value={username}
            onChange={(e) => setUsername(e.target.value.toUpperCase())}
            autoComplete="username"
            placeholder="Ingresa tu nombre de usuario"
            required
          />
          {location.state?.passwordChanged && <p className="alert alert-info">Contraseña actualizada. Inicia sesión nuevamente.</p>}
          {location.state?.sessionExpired && <p className="alert alert-warning">La sesión venció o fue revocada. Inicia sesión nuevamente.</p>}
          <Input
            label="Contraseña"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value.toUpperCase())}
            autoComplete="current-password"
            placeholder="Ingresa tu contraseña"
            required
          />
          {error && (
            <div className="alert alert-error">
              {error}
            </div>
          )}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? 'Ingresando...' : 'Ingresar'}
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-text-secondary">
          Solicita tus credenciales al administrador del sistema.
        </p>
          <span className="mt-4 block text-center text-xs text-text-secondary">Version 0.1.0</span>
        {localStorage.getItem('vistageo_jornada_habilitada') === 'true' && (
          <p className="mt-4 text-center text-sm"><Link className="font-semibold text-blue-700" to="/jornada/camara">Abrir fotos de jornada en este dispositivo</Link></p>
        )}
      </div>
    </div>
  )
}
