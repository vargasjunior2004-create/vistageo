import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { SkeletonCard } from '../components/Skeleton'
import type { Role } from '../types/api'

export function RolesPage() {
  const { user, hasPermission } = useAuth()
  const isManager = ['ADMINISTRADOR', 'GERENCIA', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const canConsult = isManager || hasPermission('roles.consultar')
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [editingPerms, setEditingPerms] = useState<Role | null>(null)
  const [selectedPerms, setSelectedPerms] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [r, p] = await Promise.all([
        apiRequest<Role[]>('/roles'),
        isManager ? apiRequest<string[]>('/permisos') : Promise.resolve([]),
      ])
      setRoles(r)
      setPermissions(p)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
      setLoaded(true)
    }
  }, [isManager])

  useEffect(() => {
    load()
  }, [load])

  const savePerms = async () => {
    if (!editingPerms) return
    setError('')
    try {
      await apiRequest(`/roles/${editingPerms.id}/permisos`, {
        method: 'PUT',
        body: { permissions: selectedPerms },
      })
      setEditingPerms(null)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (!canConsult) {
    return <p className="text-slate-600">No autorizado.</p>
  }

  return (
    <div className="space-y-4">
      <h1 className="page-title">Roles y permisos</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {loading && !loaded ? <div role="status" aria-label="Cargando roles" className="space-y-3">
        {Array.from({ length: 3 }, (_, index) => <SkeletonCard key={index} rows={2} />)}
      </div> : (
        <div className="space-y-3">
          {roles.length === 0 && !error ? <p className="rounded-xl bg-white p-5 text-slate-600">No hay roles disponibles.</p> : roles.map((role) => (
            <div key={role.id} className="surface-panel p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="font-semibold text-slate-900">{role.name}</h2>
                  <p className="text-xs text-slate-500">{role.permissions.join(', ') || 'Sin permisos'}</p>
                </div>
                <div className="flex gap-2">
                  {isManager && (user?.role_name === 'ADMINISTRADOR' || role.name !== 'ADMINISTRADOR') && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setEditingPerms(role)
                        setSelectedPerms(role.permissions)
                      }}
                    >
                      Permisos
                    </Button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {editingPerms && (
        <div className="surface-panel p-5">
          <h2 className="mb-2 font-semibold">Permisos de {editingPerms.name}</h2>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {permissions.map((p) => (
              <label key={p} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedPerms.includes(p)}
                  onChange={(e) => {
                    if (e.target.checked) setSelectedPerms([...selectedPerms, p])
                    else setSelectedPerms(selectedPerms.filter((x) => x !== p))
                  }}
                />
                {p}
              </label>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button onClick={savePerms}>Guardar</Button>
            <Button variant="secondary" onClick={() => setEditingPerms(null)}>Cancelar</Button>
          </div>
        </div>
      )}
    </div>
  )
}
