import { useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const navItems = [
  { to: '/', label: 'Inicio', icon: '⌂' },
  { to: '/usuarios', label: 'Usuarios', permission: 'usuarios.consultar' },
  { to: '/roles', label: 'Roles', permission: 'roles.consultar' },
  { to: '/ubicaciones', label: 'Ubicaciones', admin: true },
]

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout, hasPermission } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')

  const permissionManager = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const visible = navItems.filter((item) =>
    !(user?.role_name === 'TECNICO' && (item.to === '/usuarios' || item.to === '/roles')) &&
    (!item.admin || user?.role_name === 'ADMINISTRADOR') &&
    (!item.permission || hasPermission(item.permission) || (item.to === '/roles' && permissionManager)),
  )

  const signOut = async () => {
    try {
      await logout()
      navigate('/login')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cerrar sesión')
    }
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-white/60 bg-white/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-teal-700 text-sm font-bold text-white shadow-lg shadow-teal-600/30">
              VG
            </span>
            <span className="text-lg font-bold tracking-tight text-slate-900">VISTA GEO</span>
          </Link>
          <button
            className="rounded-xl p-2 text-slate-600 hover:bg-slate-100 md:hidden"
            onClick={() => setOpen((v) => !v)}
            aria-label="Menú"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <nav className="hidden items-center gap-1 md:flex">
            {visible.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-xl px-3.5 py-2 text-sm font-medium transition ${isActive ? 'bg-teal-50 text-teal-700' : 'text-slate-600 hover:bg-slate-100'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <div className="ml-2 flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-1.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-amber-400 to-amber-600 text-xs font-bold text-white">
                {user?.username?.slice(0, 2) ?? 'U'}
              </span>
              <span className="text-sm font-medium text-slate-700">{user?.username}</span>
            </div>
            <button
              onClick={signOut}
              className="rounded-xl px-3 py-2 text-sm font-medium text-slate-500 hover:bg-rose-50 hover:text-rose-600"
            >
              Salir
            </button>
          </nav>
        </div>
        {open && (
          <div className="border-t border-slate-100 bg-white/95 px-4 py-2 md:hidden">
            {visible.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className={({ isActive }) =>
                  `block rounded-xl px-3 py-2.5 text-sm font-medium ${isActive ? 'bg-teal-50 text-teal-700' : 'text-slate-600'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              onClick={signOut}
              className="block w-full rounded-xl px-3 py-2.5 text-left text-sm font-medium text-rose-600"
            >
              Cerrar sesión
            </button>
          </div>
        )}
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {error && <p role="alert" className="mb-4 text-sm text-red-600">{error}</p>}
        {children}
      </main>
    </div>
  )
}
