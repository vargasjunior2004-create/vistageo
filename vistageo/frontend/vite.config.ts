import { createHash } from 'node:crypto'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

function offlineShell(): Plugin {
  return {
    name: 'vista-geo-offline-shell',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const assets = Object.keys(bundle).filter((name) => name.startsWith('assets/') && !name.endsWith('.map'))
      const files = ['/index.html', '/manifest.webmanifest', '/favicon.svg', ...assets.map((name) => `/${name}`)]
      const version = createHash('sha256').update(files.join('|')).digest('hex').slice(0, 16)
      const source = `
const CACHE = ${JSON.stringify(`vistageo-shell-${version}`)};
const FILES = ${JSON.stringify(files)};
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('vistageo-shell-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return;
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.open(CACHE).then(cache => cache.match('/index.html'))));
  } else if (FILES.includes(url.pathname)) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(url.pathname)).then(response => response || fetch(request)));
  }
});`
      this.emitFile({ type: 'asset', fileName: 'service-worker.js', source })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), offlineShell()],
})
