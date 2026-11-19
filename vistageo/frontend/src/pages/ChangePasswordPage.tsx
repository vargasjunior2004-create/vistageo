import { useState } from 'react'
import { apiRequest } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Input } from '../components/Input'

export function ChangePasswordPage() {
  const { clearSession } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (next.length < 8) {
      setError('La nueva contraseña debe tener al menos 8 caracteres')
      return
    }
    if (next !== confirm) {
      setError('Las contraseñas no coinciden')
      return
    }
    setLoading(true)
    try {
      await apiRequest('/auth/password', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      })
      clearSession(true)
    } catch (err) {
      setError((err as Error).message || 'No fue posible cambiar la contraseña')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="mb-4 text-2xl font-bold text-slate-900">Cambiar contraseña</h1>
      <form onSubmit={submit} className="space-y-4 rounded-3xl bg-white p-6 shadow-xl shadow-slate-200/50 ring-1 ring-slate-100">
        <Input label="Contraseña actual" type="password" value={current} onChange={(e) => setCurrent(e.target.value.toUpperCase())} required />
        <Input label="Nueva contraseña" type="password" value={next} onChange={(e) => setNext(e.target.value.toUpperCase())} required />
        <Input label="Confirmar nueva contraseña" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value.toUpperCase())} required />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <Button type="submit" disabled={loading}>{loading ? 'Guardando...' : 'Guardar'}</Button>
      </form>
    </div>
  )
}
