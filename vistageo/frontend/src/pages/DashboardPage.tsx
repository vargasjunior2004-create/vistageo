import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/Icon'

type Action = { to: string; title: string; description: string; icon: IconName; enabled: boolean }

export function DashboardPage() {
  const { user, hasPermission } = useAuth()
  const fieldRole = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user?.role_name ?? '')
  const groups: { title: string; description: string; actions: Action[] }[] = [
    {
      title: 'Ubicaciones',
      description: 'Registra o encuentra una fachada por kardex.',
      actions: [
        { to: '/registrar-ubicacion', title: 'Registrar ubicación', description: 'Guarda una nueva fachada y su ubicación GPS.', icon: 'register', enabled: hasPermission('ubicaciones.registrar') },
        { to: '/consultar-ubicacion', title: 'Consultar ubicación', description: 'Busca una ubicación existente por kardex.', icon: 'search', enabled: hasPermission('ubicaciones.consultar') },
      ],
    },
    {
      title: 'Fotos de jornada',
      description: 'Tus fotos de trabajo permanecen en este dispositivo.',
      actions: [
        { to: '/jornada/camara', title: 'Sacar fotos de jornada', description: 'Abre la cámara y guarda fotos de tu trabajo.', icon: 'camera', enabled: fieldRole },
        { to: '/jornada/fotos', title: 'Mis fotos', description: 'Revisa, selecciona y comparte tus fotos.', icon: 'photos', enabled: fieldRole },
      ],
    },
  ]

  return (
    <div className="mx-auto max-w-5xl">
      <header className="border-b border-slate-200 pb-7 sm:pb-9">
        <p className="text-xs font-bold tracking-[0.14em] text-blue-700 uppercase">Panel de campo</p>
        <h1 className="font-display mt-3 text-3xl font-bold tracking-tight text-[#102c50] sm:text-4xl">Tu trabajo, en un lugar</h1>
        <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600 sm:text-base">Elige una acción para continuar con tu jornada.</p>
        <p className="mt-5 text-sm text-slate-500">{user?.username} <span aria-hidden="true" className="mx-1 text-slate-300">/</span> {user?.role_name}</p>
      </header>
      <div className="space-y-9 py-7 sm:py-9">
        {groups.map((group) => {
          const actions = group.actions.filter((action) => action.enabled)
          if (!actions.length) return null
          return (
            <section key={group.title} aria-label={group.title}>
              <div className="mb-4">
                <h2 className="font-display text-lg font-bold text-[#102c50]">{group.title}</h2>
                <p className="mt-1 text-sm text-slate-500">{group.description}</p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {actions.map((action) => (
                  <Link key={action.to} to={action.to} className="group flex min-h-32 items-start gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm hover:border-blue-300 hover:bg-blue-50/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700">
                    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><Icon name={action.icon} className="h-6 w-6" /></span>
                    <span className="min-w-0 flex-1">
                      <strong className="block text-base font-bold text-[#102c50]">{action.title}</strong>
                      <span className="mt-1 block text-sm leading-5 text-slate-600">{action.description}</span>
                    </span>
                    <Icon name="arrow" className="mt-1 h-5 w-5 shrink-0 text-blue-600" />
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
