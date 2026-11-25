import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { transformWithOxc } from 'vite'

const source = await readFile(new URL('../src/services/cameraDiagnostics.ts', import.meta.url), 'utf8')
const { code } = await transformWithOxc(source, 'cameraDiagnostics.ts')
const storage = new Map()
globalThis.window = {
  localStorage: {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  },
}
const originalInfo = console.info
console.info = () => {}
const { beginCameraAttempt, recordCameraEvent } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('persists attempt numbers and caps diagnostic history without photo contents', (context) => {
  context.after(() => { console.info = originalInfo })

  assert.equal(beginCameraAttempt('camera'), 1)
  recordCameraEvent('selection_received', { fileSize: 1024, mimeType: 'image/jpeg' })
  assert.equal(beginCameraAttempt('camera'), 2)
  for (let index = 0; index < 105; index += 1) recordCameraEvent('document_visibility_changed', { visible: true })

  const state = JSON.parse(storage.get('vistageo_camera_diagnostics'))
  assert.equal(state.attempt, 2)
  assert.equal(state.events.length, 100)
  assert.equal(state.events[0].attempt, 2)
  assert.equal(state.events.some((event) => 'photo' in event.details || 'uri' in event.details), false)
})
