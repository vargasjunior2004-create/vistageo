import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { toast } from 'sonner'
import { transformWithOxc } from 'vite'

const source = await readFile(new URL('../src/services/notifications.ts', import.meta.url), 'utf8')
const { code } = await transformWithOxc(source, 'notifications.ts')
const resolved = code.replace(/from ["']sonner["']/, `from '${import.meta.resolve('sonner')}'`)
const { notifications } = await import(`data:text/javascript;base64,${Buffer.from(resolved).toString('base64')}`)

test('agrupa notificaciones idénticas sin mezclar tipos', () => {
  notifications.success('Prueba duplicada')
  notifications.success('Prueba duplicada')
  notifications.error('Prueba duplicada')
  const matching = toast.getToasts().filter((item) => item.title === 'Prueba duplicada')
  assert.equal(matching.length, 2)
  assert.deepEqual(matching.map((item) => item.type), ['success', 'error'])
})

test('una clave compartida sustituye resultados anteriores de la misma consulta', () => {
  notifications.success('Disponible', 'test-consulta')
  notifications.warning('Registrado', 'test-consulta')
  const matching = toast.getToasts().filter((item) => item.id === 'test-consulta')
  assert.equal(matching.length, 1)
  assert.equal(matching[0].title, 'Registrado')
  assert.equal(matching[0].type, 'warning')
})
