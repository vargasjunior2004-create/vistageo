import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/Icon'

type Action = { to: string; title: string; description: string; icon: IconName; enabled: boolean }

export function DashboardPage() {
  const { user, hasPermission } = useAuth()
  const fieldRole = ['ADMINISTRADOR', 'GERENCIA', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user?.role_name ?? '')
  const groups: { title: string; description: string; actions: Action[] }[] = [
    {
      title: 'Ubicaciones',
      description: 'Registra una fachada o consulta un kardex.',
      actions: [
        { to: '/registrar-ubicacion', title: 'Registrar ubicación', description: 'Guarda una nueva fachada y su ubicación GPS.', icon: 'register', enabled: hasPermission('ubicaciones.registrar') },
        { to: '/consultar-ubicacion', title: 'Consultar ubicación', description: 'Busca una ubicación existente por kardex.', icon: 'search', enabled: hasPermission('ubicaciones.consultar') },
      ],
    },
    {
      title: 'Fotos de jornada',
      description: 'Captura y revisa fotos guardadas en este dispositivo.',
      actions: [
        { to: '/jornada/camara', title: 'Sacar fotos de jornada', description: 'Abre la cámara y guarda fotos de tu trabajo.', icon: 'camera', enabled: fieldRole },
        { to: '/jornada/fotos', title: 'Mis fotos', description: 'Revisa, selecciona y comparte tus fotos.', icon: 'photos', enabled: fieldRole },
      ],
    },
  ]

  return (
    <div className="mx-auto max-w-6xl">
      <header className="border-b border-border pb-6 sm:pb-8">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-action-strong">Panel de campo</p>
        <h1 className="page-title mt-2 text-3xl sm:text-4xl">Ubicaciones de clientes</h1>
        <p className="page-description mt-3 max-w-xl">Registra una fachada con sus coordenadas y fotografía, o consulta un kardex existente.</p>
        <p className="mt-4 text-sm text-slate-500">{user?.username} <span aria-hidden="true" className="mx-1 text-slate-300">/</span> {user?.role_name}</p>
      </header>
      <div className="space-y-7 py-6 sm:py-8">
        {groups.map((group) => {
          const actions = group.actions.filter((action) => action.enabled)
          if (!actions.length) return null
          return (
            <section key={group.title} aria-label={group.title}>
              <div className="mb-4">
                <h2 className="text-lg font-semibold text-primary">{group.title}</h2>
                <p className="mt-1 text-sm text-slate-600">{group.description}</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {actions.map((action) => (
                  <Link key={action.to} to={action.to} className={`dashboard-action group flex items-start gap-4 border p-4 transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action sm:p-5 ${action.to === '/registrar-ubicacion' ? 'dashboard-action-primary' : ''}`}>
                    <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${action.to === '/registrar-ubicacion' ? 'bg-white/10 text-white' : 'bg-blue-50 text-action-strong'}`}><Icon name={action.icon} className="h-5 w-5" /></span>
                    <span className="min-w-0 flex-1">
                      <strong className="block text-base font-medium">{action.title}</strong>
                      <span className={`mt-1 block text-sm leading-5 ${action.to === '/registrar-ubicacion' ? 'text-blue-100' : 'text-text-secondary'}`}>{action.description}</span>
                    </span>
                    <Icon name="arrow" className={`mt-1 h-5 w-5 shrink-0 ${action.to === '/registrar-ubicacion' ? 'text-blue-100' : 'text-slate-400 group-hover:text-action-strong'}`} />
                  </Link>
                ))}
              </div>
            </section>
          )
        })}
      </div>
    </div>
  )
}
