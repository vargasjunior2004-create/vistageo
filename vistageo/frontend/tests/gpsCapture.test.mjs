import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { transformWithOxc } from 'vite'

const source = await readFile(new URL('../src/services/gpsCapture.ts', import.meta.url), 'utf8')
const { code: javascript } = await transformWithOxc(source, 'gpsCapture.ts')
const { gpsQuality, isGpsPositionValid } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`)

const limits = { excelente: 5, buena: 10, aceptable: 20, baja: 50 }

test('clasifica sin redondear, incluidos todos los límites', () => {
  for (const [value, expected] of [
    [0, 'Excelente'], [5, 'Excelente'], [5.0001, 'Buena'], [10, 'Buena'],
    [10.0001, 'Aceptable'], [20, 'Aceptable'], [20.0001, 'Baja'],
    [50, 'Baja'], [50.0001, 'Deficiente'],
  ]) assert.equal(gpsQuality(value, limits), expected)
})

test('descarta muestras anteriores, futuras y con valores GPS inválidos', () => {
  const sample = { coords: { latitude: 1, longitude: 2, accuracy: 3.125 }, timestamp: 10000 }
  assert.equal(isGpsPositionValid(sample, 10000, 10000), true)
  assert.equal(isGpsPositionValid({ ...sample, timestamp: 8999 }, 10000, 10000), false)
  assert.equal(isGpsPositionValid({ ...sample, timestamp: 15001 }, 10000, 10000), false)
  assert.equal(isGpsPositionValid({ ...sample, coords: { ...sample.coords, accuracy: NaN } }, 10000, 10000), false)
  assert.equal(isGpsPositionValid({ ...sample, coords: { ...sample.coords, latitude: 91 } }, 10000, 10000), false)
})
