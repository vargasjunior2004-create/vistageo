export type JornadaPhoto = {
  id: string
  createdAt: number
  blob: Blob
}

export type LocationDraft = {
  idempotencia: string
  kardex: string
  latitud: string
  longitud: string
  fotografia_base64: string
}

const database = 'vistageo-local'

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(database, 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('jornada', { keyPath: 'id' })
      request.result.createObjectStore('borradores')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('No se pudo abrir el almacenamiento local'))
    request.onblocked = () => reject(new Error('Cierra otras pestañas de VISTA GEO y vuelve a intentar'))
  })
}

async function transaction<T>(
  store: string, mode: IDBTransactionMode, action: (objectStore: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDatabase()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode)
    const request = action(tx.objectStore(store))
    tx.oncomplete = () => { db.close(); resolve(request.result) }
    tx.onabort = () => { db.close(); reject(new Error('No se pudo guardar en el dispositivo; revisa el espacio disponible')) }
    tx.onerror = () => { db.close(); reject(new Error('Error de almacenamiento local')) }
  })
}

export function listPhotos(): Promise<JornadaPhoto[]> {
  return transaction('jornada', 'readonly', (store) => store.getAll())
}

export async function savePhoto(blob: Blob): Promise<void> {
  const photo: JornadaPhoto = { id: crypto.randomUUID(), createdAt: Date.now(), blob }
  await transaction('jornada', 'readwrite', (store) => store.add(photo))
}

export async function deletePhotos(ids: string[]): Promise<void> {
  const db = await openDatabase()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction('jornada', 'readwrite')
    const store = tx.objectStore('jornada')
    ids.forEach((id) => store.delete(id))
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onabort = () => { db.close(); reject(new Error('No se pudieron eliminar las fotografías')) }
    tx.onerror = () => { db.close(); reject(new Error('Error de almacenamiento local')) }
  })
}

export function getDraft(userId: number): Promise<LocationDraft | undefined> {
  return transaction('borradores', 'readonly', (store) => store.get(`ubicacion:${userId}`))
}

export async function saveDraft(userId: number, draft: LocationDraft): Promise<void> {
  await transaction('borradores', 'readwrite', (store) => store.put(draft, `ubicacion:${userId}`))
}

export async function deleteDraft(userId: number): Promise<void> {
  await transaction('borradores', 'readwrite', (store) => store.delete(`ubicacion:${userId}`))
}
