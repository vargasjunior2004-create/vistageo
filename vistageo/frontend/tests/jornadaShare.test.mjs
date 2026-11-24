import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { transformWithOxc } from 'vite'

const source = await readFile(new URL('../src/services/jornadaShare.ts', import.meta.url), 'utf8')
const { code } = await transformWithOxc(source, 'jornadaShare.ts')
const { prepareJornadaShare } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

const photos = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

test('mantiene el orden de la galería y asocia cada descripción con su foto seleccionada', () => {
  const result = prepareJornadaShare(photos, ['c', 'a'], { a: 'Cambio de conector.\n123', b: 'No seleccionada', c: 'Revisión' })
  assert.deepEqual(result.photos, [photos[0], photos[2]])
  assert.equal(result.text, 'Foto 1: Cambio de conector.\n123\nFoto 2: Revisión')
})

test('incluye las fotos sin descripción en la numeración y omite el texto cuando todas están vacías', () => {
  assert.equal(prepareJornadaShare(photos, ['a', 'b', 'c'], { c: 'Cambio' }).text, 'Foto 1:\nFoto 2:\nFoto 3: Cambio')
  assert.deepEqual(prepareJornadaShare(photos, ['a'], { b: 'Otra' }), { photos: [photos[0]] })
  assert.deepEqual(prepareJornadaShare(photos, [], { a: 'Cambio' }), { photos: [] })
})
