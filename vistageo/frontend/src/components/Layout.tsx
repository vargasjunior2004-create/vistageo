import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from './Icon'

type NavItem = { to: string; label: string; icon: IconName; enabled: boolean }

export function Layout({ children, local = false }: { children: React.ReactNode; local?: boolean }) {
  const { user, logout, hasPermission } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [error, setError] = useState('')
  const menuButton = useRef<HTMLButtonElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const sidebar = useRef<HTMLElement>(null)

  const permissionManager = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const fieldRole = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user?.role_name ?? '')
  const work: NavItem[] = [
    { to: '/', label: 'Inicio', icon: 'home', enabled: true },
    { to: '/registrar-ubicacion', label: 'Registrar ubicación', icon: 'register', enabled: hasPermission('ubicaciones.registrar') },
    { to: '/consultar-ubicacion', label: 'Consultar ubicación', icon: 'search', enabled: hasPermission('ubicaciones.consultar') },
    { to: '/jornada/camara', label: 'Sacar fotos de jornada', icon: 'camera', enabled: fieldRole || local },
    { to: '/jornada/fotos', label: 'Mis fotos', icon: 'photos', enabled: fieldRole || local },
  ]
  const administration: NavItem[] = [
    { to: '/usuarios', label: 'Usuarios', icon: 'users', enabled: user?.role_name !== 'TECNICO' && hasPermission('usuarios.consultar') },
    { to: '/roles', label: 'Roles', icon: 'roles', enabled: user?.role_name !== 'TECNICO' && (hasPermission('roles.consultar') || permissionManager) },
    { to: '/ubicaciones', label: 'Ubicaciones', icon: 'locations', enabled: user?.role_name === 'ADMINISTRADOR' },
  ]
  const groups = [
    { label: 'Trabajo de campo', items: work.filter((item) => item.enabled) },
    { label: 'Administración', items: administration.filter((item) => item.enabled) },
  ]

  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    const desktop = window.matchMedia('(min-width: 1024px)')
    const onResize = () => {
      if (desktop.matches) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false)
        menuButton.current?.focus()
      } else if (event.key === 'Tab' && sidebar.current) {
        const elements = Array.from(sidebar.current.querySelectorAll<HTMLElement>('a[href], button:not([disabled])'))
          .filter((element) => element.getClientRects().length > 0)
        const first = elements[0]
        const last = elements[elements.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last?.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first?.focus()
        }
      }
    }
    document.addEventListener('keydown', onKeyDown)
    desktop.addEventListener('change', onResize)
    onResize()
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
      desktop.removeEventListener('change', onResize)
    }
  }, [open])

  const closeMenu = () => {
    setOpen(false)
    menuButton.current?.focus()
  }

  const signOut = async () => {
    try {
      await logout()
      setOpen(false)
      navigate('/login')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cerrar sesión')
      setOpen(false)
    }
  }

  return (
    <div className="min-h-screen lg:flex">
      {open && <button type="button" aria-label="Cerrar menú" onClick={closeMenu} className="fixed inset-0 z-40 bg-slate-950/60 lg:hidden" />}
      <aside
        ref={sidebar}
        id="navegacion-principal"
        role={open ? 'dialog' : undefined}
        aria-modal={open ? true : undefined}
        aria-label="Navegación principal"
        className={`${open ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-50 w-[min(19rem,85vw)] flex-col bg-[#102c50] text-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:shrink-0 ${collapsed ? 'lg:w-20' : 'lg:w-64'}`}
      >
        <div className={`flex min-h-20 items-center gap-3 border-b border-white/10 px-5 ${collapsed ? 'lg:justify-center lg:px-3' : ''}`}>
          <Link to="/" onClick={() => setOpen(false)} aria-label="VISTA GEO, inicio" className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#2f6ecb] text-white"><Icon name="locations" className="h-6 w-6" /></span>
            <span className={`min-w-0 ${collapsed ? 'lg:sr-only' : ''}`}>
              <span className="block text-base font-bold tracking-[0.08em]">VISTA GEO</span>
              <span className="block text-[11px] text-blue-200">GRUPO VISTA</span>
            </span>
          </Link>
          <button ref={closeButton} type="button" onClick={closeMenu} aria-label="Cerrar menú" className="ml-auto flex h-11 w-11 items-center justify-center rounded-lg text-blue-100 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-white lg:hidden">
            <Icon name="close" className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-6" aria-label="Secciones">
          {groups.filter((group) => group.items.length > 0).map((group) => (
            <div key={group.label}>
              <p className={`mb-2 px-3 text-[10px] font-bold tracking-[0.13em] text-blue-200/80 uppercase ${collapsed ? 'lg:sr-only' : ''}`}>{group.label}</p>
              <ul className="space-y-1">
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={item.to === '/'}
                      onClick={() => setOpen(false)}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) => `flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${collapsed ? 'lg:justify-center lg:px-0' : ''} ${isActive ? 'bg-[#2f6ecb] text-white' : 'text-blue-100 hover:bg-white/10 hover:text-white'}`}
                    >
                      <Icon name={item.icon} className="h-5 w-5 shrink-0" />
                      <span className={collapsed ? 'lg:sr-only' : ''}>{item.label}</span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="border-t border-white/10 p-3">
          {user ? <>
            <div className={`flex min-w-0 items-center gap-3 rounded-xl px-3 py-3 ${collapsed ? 'lg:justify-center lg:px-0' : ''}`}>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold">{user.username.slice(0, 2)}</span>
              <span className={`min-w-0 ${collapsed ? 'lg:sr-only' : ''}`}>
                <span className="block truncate text-sm font-semibold">{user.username}</span>
                <span className="block truncate text-xs text-blue-200">{user.role_name}</span>
              </span>
            </div>
            <button type="button" onClick={() => void signOut()} title={collapsed ? 'Cerrar sesión' : undefined} className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm font-medium text-blue-100 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-white ${collapsed ? 'lg:justify-center lg:px-0' : ''}`}>
              <Icon name="logout" className="h-5 w-5 shrink-0" /><span className={collapsed ? 'lg:sr-only' : ''}>Cerrar sesión</span>
            </button>
          </> : <Link to="/login" onClick={() => setOpen(false)} className="flex min-h-11 items-center rounded-xl px-3 text-sm font-medium text-blue-100 hover:bg-white/10">Iniciar sesión</Link>}
          <button type="button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? 'Expandir barra lateral' : 'Contraer barra lateral'} title={collapsed ? 'Expandir barra lateral' : 'Contraer barra lateral'} className={`mt-1 hidden min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left text-sm text-blue-200 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-white lg:flex ${collapsed ? 'lg:justify-center lg:px-0' : ''}`}>
            <Icon name={collapsed ? 'expand' : 'collapse'} className="h-5 w-5 shrink-0" /><span className={collapsed ? 'lg:sr-only' : ''}>Contraer barra</span>
          </button>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex min-h-16 items-center gap-3 border-b border-slate-200 bg-white px-4 sm:px-7 lg:px-10">
          <button ref={menuButton} type="button" onClick={() => setOpen(true)} aria-label="Abrir menú" aria-expanded={open} aria-controls="navegacion-principal" className="flex h-11 w-11 items-center justify-center rounded-xl text-[#102c50] hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-700 lg:hidden">
            <Icon name="menu" className="h-6 w-6" />
          </button>
          <span className="text-sm font-bold tracking-wide text-[#102c50] lg:hidden">VISTA GEO</span>
          <span className="hidden text-sm font-medium text-slate-500 lg:block">Grupo Vista <span className="mx-2 text-slate-300">/</span> Panel de trabajo</span>
          {local && <span className="ml-auto text-xs font-medium text-slate-500">Fotos en este dispositivo</span>}
        </header>
        <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-7 sm:py-8 lg:px-10">
          {error && <p role="alert" className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          {children}
        </main>
      </div>
    </div>
  )
}
