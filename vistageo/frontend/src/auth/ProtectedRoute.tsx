import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

export function ProtectedRoute({ children }: { children: React.JSX.Element }) {
  const { user, loading, error, passwordChanged, sessionExpired, refresh } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-600">
        Cargando...
      </div>
    )
  }

  if (error) {
    return <div role="alert" className="space-y-4 p-6">
      <p>No se pudo verificar la sesión: {error}. <button onClick={() => void refresh()} className="font-semibold text-blue-700">Reintentar</button></p>
      {localStorage.getItem('vistageo_jornada_habilitada') === 'true' && <p><Link className="font-semibold text-blue-700" to="/jornada/camara">Abrir fotos de jornada en este dispositivo</Link></p>}
    </div>
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location, passwordChanged, sessionExpired }} replace />
  }

  if (user.must_change_password && location.pathname !== '/cambiar-contrasena') {
    return <Navigate to="/cambiar-contrasena" replace />
  }

  return children
}
