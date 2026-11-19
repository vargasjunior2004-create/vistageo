import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import type { Role } from '../types/api'

export function RolesPage() {
  const { user, hasPermission } = useAuth()
  const canManage = hasPermission('roles.gestionar')
  const isManager = ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const canConsult = isManager || hasPermission('roles.consultar')
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [newRole, setNewRole] = useState('')
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
    }
  }, [isManager])

  useEffect(() => {
    load()
  }, [load])

  const createRole = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newRole.trim()) return
    setError('')
    try {
      await apiRequest('/roles', { method: 'POST', body: { name: newRole } })
      setNewRole('')
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const renameRole = async (role: Role, name: string) => {
    setError('')
    try {
      await apiRequest(`/roles/${role.id}`, { method: 'PATCH', body: { name } })
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

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
      <h1 className="text-2xl font-bold text-slate-900">Roles y permisos</h1>
      {error && <p className="text-sm text-red-600">{error}</p>}

      {canManage && (
        <form onSubmit={createRole} className="flex flex-wrap items-end gap-2 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <div className="flex-1">
            <Input label="Nuevo rol" value={newRole} onChange={(e) => setNewRole(e.target.value.toUpperCase())} />
          </div>
          <Button type="submit">Crear rol</Button>
        </form>
      )}

      {loading ? (
        <p className="text-slate-500">Cargando...</p>
      ) : (
        <div className="space-y-3">
          {roles.map((role) => (
            <div key={role.id} className="rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="font-semibold text-slate-900">{role.name}</h2>
                  <p className="text-xs text-slate-500">{role.permissions.join(', ') || 'Sin permisos'}</p>
                </div>
                <div className="flex gap-2">
                  {canManage && !['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(role.name) && (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        const name = prompt('Nuevo nombre', role.name)
                        if (name) renameRole(role, name.toUpperCase())
                      }}
                    >
                      Renombrar
                    </Button>
                  )}
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
        <div className="rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
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
