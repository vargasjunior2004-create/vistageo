import { useCallback, useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'
import type { UpdateReason } from '../types/api'

export function UpdateReasonsPage() {
  const { user } = useAuth()
  const allowed = ['ADMINISTRADOR', 'GERENCIA', 'GERENTE', 'JEFE COMERCIAL', 'JEFE OPERATIVO'].includes(user?.role_name ?? '')
  const [reasons, setReasons] = useState<UpdateReason[]>([])
  const [name, setName] = useState('')
  const [editing, setEditing] = useState<UpdateReason | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setReasons(await apiRequest<UpdateReason[]>('/motivos-actualizacion?todos=true'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudieron cargar los motivos.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (allowed) void load() }, [allowed, load])

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError('')
    try {
      await apiRequest(editing ? `/motivos-actualizacion/${editing.id}` : '/motivos-actualizacion', {
        method: editing ? 'PUT' : 'POST',
        body: editing ? { nombre: name, activo: editing.activo } : { nombre: name },
      })
      setName('')
      setEditing(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo guardar el motivo.')
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (reason: UpdateReason) => {
    setBusy(true)
    setError('')
    try {
      await apiRequest(`/motivos-actualizacion/${reason.id}`, {
        method: 'PUT', body: { nombre: reason.nombre, activo: !reason.activo },
      })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se pudo cambiar el estado.')
    } finally {
      setBusy(false)
    }
  }

  if (!allowed) return <p>No tienes permiso para administrar motivos.</p>
  return <div className="mx-auto max-w-3xl space-y-4">
    <h1 className="page-title">Motivos de actualización</h1>
    <p className="text-sm text-slate-600">Los motivos inactivos se conservan en el historial, pero no se pueden seleccionar.</p>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <form onSubmit={save} className="surface-panel flex flex-wrap items-end gap-3 p-5">
      <div className="min-w-52 flex-1"><Input label={editing ? 'Editar motivo' : 'Nuevo motivo'} maxLength={160} value={name} onChange={(event) => setName(event.target.value)} /></div>
      <Button type="submit" disabled={busy || !name.trim()}>{editing ? 'Guardar cambios' : 'Agregar motivo'}</Button>
      {editing && <Button type="button" variant="secondary" disabled={busy} onClick={() => { setEditing(null); setName('') }}>Cancelar</Button>}
    </form>
    {loading ? <p>Cargando motivos...</p> : reasons.length === 0 ? <p>No hay motivos registrados.</p> :
      <ul className="space-y-2">{reasons.map((reason) => <li key={reason.id} className="surface-panel flex flex-wrap items-center justify-between gap-3 p-4">
        <div><p className="font-semibold">{reason.nombre}</p><p className="text-sm text-slate-600">{reason.activo ? 'Activo' : 'Inactivo'}</p></div>
        <div className="flex gap-2"><Button type="button" variant="secondary" disabled={busy} onClick={() => { setEditing(reason); setName(reason.nombre) }}>Editar</Button>
          <Button type="button" variant="secondary" disabled={busy || !!editing} onClick={() => void toggle(reason)}>{reason.activo ? 'Desactivar' : 'Activar'}</Button></div>
      </li>)}</ul>}
  </div>
}
