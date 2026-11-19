import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { Layout } from './components/Layout'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { ContractsPage } from './pages/ContractsPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { LocationsPage } from './pages/LocationsPage'
import { RolesPage } from './pages/RolesPage'
import { SourcesPage } from './pages/SourcesPage'
import { UsersPage } from './pages/UsersPage'
import { FieldLocationPage } from './pages/FieldLocationPage'
import { LocationSearchPage } from './pages/LocationSearchPage'
import { JornadaPage } from './pages/JornadaPage'

function LocalJornada({ mode }: { mode: 'camera' | 'gallery' }) {
  if (localStorage.getItem('vistageo_jornada_habilitada') !== 'true') {
    return <div className="p-6">Inicia sesión con conexión al menos una vez para activar las fotos locales. <a href="/login">Iniciar sesión</a></div>
  }
  return <JornadaPage mode={mode} />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/jornada/camara" element={<LocalJornada mode="camera" />} />
          <Route path="/jornada/fotos" element={<LocalJornada mode="gallery" />} />
          <Route
            path="/cambiar-contrasena"
            element={
              <ProtectedRoute>
                <Layout>
                  <ChangePasswordPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <Layout>
                  <Routes>
                    <Route path="/" element={<DashboardPage />} />
                    <Route path="/usuarios" element={<UsersPage />} />
                    <Route path="/roles" element={<RolesPage />} />
                    <Route path="/contratos" element={<ContractsPage />} />
                    <Route path="/ubicaciones" element={<LocationsPage />} />
                    <Route path="/registrar-ubicacion" element={<FieldLocationPage />} />
                    <Route path="/consultar-ubicacion" element={<LocationSearchPage />} />
                    <Route path="/procedencia" element={<SourcesPage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </Layout>
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
