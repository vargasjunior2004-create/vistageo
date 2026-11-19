import { useAuth } from '../auth/AuthContext'
import { Link } from 'react-router-dom'

export function DashboardPage() {
  const { user, hasPermission } = useAuth()
  const fieldRole = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'TECNICO', 'CAJERO', 'CALL CENTER'].includes(user?.role_name ?? '')
  const cards = [
    { to: '/registrar-ubicacion', title: 'Registrar ubicación', description: 'Kardex, fachada y GPS', icon: '＋', color: 'bg-blue-700', enabled: hasPermission('ubicaciones.registrar') },
    { to: '/consultar-ubicacion', title: 'Consultar ubicación', description: 'Encuentra un cliente por kardex', icon: '⌕', color: 'bg-cyan-700', enabled: hasPermission('ubicaciones.consultar') },
    { to: '/jornada/camara', title: 'Sacar fotos de jornada', description: 'Fotos de tu jornada en el teléfono', icon: '◉', color: 'bg-blue-800', enabled: fieldRole },
    { to: '/jornada/fotos', title: 'Mis fotos', description: 'Revisa y comparte tus fotos', icon: '▦', color: 'bg-blue-600', enabled: fieldRole },
  ]
  return (
    <div className="space-y-5">
      <header className="rounded-3xl bg-[#102c50] p-6 text-white sm:p-8">
        <p className="text-sm font-semibold text-blue-200">VISTA GEO · GRUPO VISTA</p>
        <h1 className="mt-2 text-2xl font-bold sm:text-3xl">Tu jornada, en un lugar</h1>
        <p className="mt-2 text-sm text-blue-100">{user?.username} · {user?.role_name}</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-2">
        {cards.filter((card) => card.enabled).map((card) => (
          <Link key={card.to} to={card.to} className={`${card.color} flex min-h-36 items-start gap-4 rounded-3xl p-5 text-white shadow-sm transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700`}>
            <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-white/20 text-3xl">{card.icon}</span>
            <span className="flex-1"><strong className="block text-lg">{card.title}</strong><span className="mt-1 block text-sm text-white/85">{card.description}</span></span>
            <span aria-hidden="true" className="text-xl">↗</span>
          </Link>
        ))}
      </div>
    </div>
  )
}
