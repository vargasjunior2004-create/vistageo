import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import type { Role, UserRead } from '../types/api'

type UserForm = { username: string; password: string; role_id: number }

export function UsersPage() {
  const { user, hasPermission } = useAuth()
  const canManage = hasPermission('usuarios.gestionar')
  const canListRoles = hasPermission('roles.consultar') ||
    ['ADMINISTRADOR', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const [users, setUsers] = useState<UserRead[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<UserForm>({ username: '', password: '', role_id: 0 })
  const [editing, setEditing] = useState<UserRead | null>(null)
  const [resetting, setResetting] = useState<UserRead | null>(null)
  const [tempPassword, setTempPassword] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [u, r] = await Promise.all([
        apiRequest<UserRead[]>('/usuarios'),
        canListRoles ? apiRequest<Role[]>('/roles') : Promise.resolve([]),
      ])
      setUsers(u)
      setRoles(r)
      if (!form.role_id && r.length) setForm((f) => ({ ...f, role_id: r[0].id }))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }, [form.role_id, canListRoles])

  useEffect(() => {
    load()
  }, [load])

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await apiRequest('/usuarios', {
        method: 'POST',
        body: { username: form.username, password: form.password, role_id: form.role_id },
      })
      setCreating(false)
      setForm({ username: '', password: '', role_id: roles[0]?.id ?? 0 })
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editing) return
    setError('')
    try {
      await apiRequest(`/usuarios/${editing.id}`, {
        method: 'PATCH',
        body: {
          username: editing.username,
          ...(canListRoles ? { role_id: editing.role_id } : {}),
          active: editing.active,
        },
      })
      setEditing(null)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const resetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!resetting) return
    setError('')
    try {
      await apiRequest(`/usuarios/${resetting.id}/restablecer-contrasena`, {
        method: 'POST',
        body: { temporary_password: tempPassword },
      })
      setResetting(null)
      setTempPassword('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const roleName = (id: number) => roles.find((r) => r.id === id)?.name ?? id

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">Usuarios</h1>
        {canManage && canListRoles && (
          <Button onClick={() => setCreating(true)}>Nuevo usuario</Button>
        )}
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {canManage && !canListRoles && <p className="text-sm text-slate-600">Para crear usuarios o cambiar roles se requiere acceso a la lista de roles.</p>}

      {creating && (
        <form onSubmit={createUser} className="space-y-3 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <h2 className="font-semibold">Crear usuario</h2>
          <Input label="Usuario" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value.toUpperCase() })} required />
          <Input label="Contraseña" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value.toUpperCase() })} required />
          {canListRoles && <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Rol</span>
            <select
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={form.role_id}
              onChange={(e) => setForm({ ...form, role_id: Number(e.target.value) })}
            >
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </label>}
          <div className="flex gap-2">
            <Button type="submit">Crear</Button>
            <Button type="button" variant="secondary" onClick={() => setCreating(false)}>Cancelar</Button>
          </div>
        </form>
      )}

      {editing && (
        <form onSubmit={saveEdit} className="space-y-3 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <h2 className="font-semibold">Editar usuario #{editing.id}</h2>
          <Input label="Usuario" value={editing.username} onChange={(e) => setEditing({ ...editing, username: e.target.value.toUpperCase() })} required />
          {canListRoles && <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Rol</span>
            <select
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={editing.role_id}
              onChange={(e) => setEditing({ ...editing, role_id: Number(e.target.value) })}
            >
              {roles.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          </label>}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={editing.active}
              onChange={(e) => setEditing({ ...editing, active: e.target.checked })}
            />
            Activo
          </label>
          <div className="flex gap-2">
            <Button type="submit">Guardar</Button>
            <Button type="button" variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          </div>
        </form>
      )}

      {resetting && (
        <form onSubmit={resetPassword} className="space-y-3 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <h2 className="font-semibold">Restablecer contraseña de {resetting.username}</h2>
          <Input label="Contraseña temporal" type="password" value={tempPassword} onChange={(e) => setTempPassword(e.target.value.toUpperCase())} required />
          <div className="flex gap-2">
            <Button type="submit">Restablecer</Button>
            <Button type="button" variant="secondary" onClick={() => { setResetting(null); setTempPassword('') }}>Cancelar</Button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-slate-500">Cargando...</p>
      ) : (
        <div className="overflow-x-auto rounded-3xl bg-white shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Usuario</th>
                <th className="px-4 py-3">Rol</th>
                <th className="px-4 py-3">Estado</th>
                {canManage && <th className="px-4 py-3">Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="px-4 py-3">{u.id}</td>
                  <td className="px-4 py-3 font-medium">{u.username}</td>
                  <td className="px-4 py-3">{roleName(u.role_id)}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-1 text-xs ${u.active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {u.active ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  {canManage && (
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" onClick={() => setEditing(u)}>Editar</Button>
                        <Button variant="ghost" onClick={() => setResetting(u)}>Reset</Button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
