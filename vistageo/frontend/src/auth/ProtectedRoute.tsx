import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { SkeletonDashboard } from '../components/Skeleton'

export function ProtectedRoute({ children }: { children: React.JSX.Element }) {
  const { user, loading, error, passwordChanged, sessionExpired, refresh } = useAuth()
  const location = useLocation()

  if (loading) {
    return <SkeletonDashboard />
  }

  if (error) {
    return <div role="alert" className="alert alert-error m-6 space-y-4">
      <p>No se pudo verificar la sesión: {error}. <button onClick={() => void refresh()} className="font-semibold text-action-strong underline">Reintentar</button></p>
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
