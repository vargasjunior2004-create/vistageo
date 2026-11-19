# VISTA GEO Frontend

Frontend React + TypeScript + Tailwind CSS (Mobile First) para la API de GEO VISTA.

## Requisitos

- Node.js 20+
- Backend FastAPI ejecutándose y accesible.

## Configuración

```sh
cp .env.example .env.local
# Editar VITE_API_URL si el backend no está en localhost:8000
npm install
npm run dev
```

En el backend configurar `CORS_ORIGINS=http://localhost:5173` para el origen
predeterminado de Vite y reiniciar FastAPI. Si Vite utiliza otro puerto,
configurar ese origen exacto. Sin `VITE_API_URL`, el frontend utiliza el mismo
origen; no incluye ninguna clave de Supabase.

## Render

Crear un **Static Site** con raíz `vistageo/frontend`, build `npm ci && npm run
build` y directorio publicado `dist`. Configurar en el sitio `VITE_API_URL`
con la URL HTTPS pública del Web Service de FastAPI, sin barra final, antes
de compilar. Agregar la regla de rewrite `/*` → `/index.html` para React
Router. En el backend configurar `CORS_ORIGINS` con el origen HTTPS exacto
del sitio estático. Son dos servicios; la clave de Storage y la conexión a
PostgreSQL solo van en el backend. La configuración no despliega ni migra
datos automáticamente.

## Scripts

- `npm run dev`: servidor de desarrollo.
- `npm run build`: compilación de producción.
- `npm run preview`: vista previa de producción.
- `npm run lint`: lint.

## Notas

- El token se guarda en `localStorage`; cerrar sesión lo elimina.
- Las acciones deliberadas envían `X-Actividad-Usuario: true`.
- El frontend no sustituye la autorización del backend; todos los permisos se verifican en la API.
- El panel muestra registro y consulta de ubicaciones según sus permisos.
  La fotografía oficial y el GPS se guardan mediante el backend. Si falla la
  conexión, se conserva un borrador local por usuario para reintentar con la
  misma operación; descartarlo puede requerir revisión manual en el servidor.
- Las fotos de jornada permanecen en IndexedDB de este navegador: no se envían
  al backend ni a Supabase. Tras iniciar sesión una vez con un rol habilitado y
  cargar la aplicación de producción, la cámara y galería pueden abrirse sin
  conexión, incluso desde el enlace de la pantalla de inicio de sesión.
- Esa galería no está protegida por sesión: cualquiera con acceso al navegador
  puede verla, aunque se cierre la sesión. Si se borran los datos del sitio o
  el navegador libera espacio, se pueden perder las fotos; no son una copia de
  seguridad ni necesariamente aparecen en la galería nativa del teléfono.
- Compartir abre el selector nativo solo si el navegador admite Web Share con
  archivos. WhatsApp debe estar disponible en el dispositivo y el usuario
  decide el destino y confirma el envío. El resultado depende del dispositivo.
- La cámara, GPS y service worker requieren HTTPS o localhost. El service worker
  solo se registra en producción y guarda recursos estáticos, no respuestas
  privadas de la API. Comprueba el funcionamiento offline en el dispositivo
  después de visitar la aplicación con conexión.
- Antes de desplegar el panel hay que revisar y autorizar por separado la
  revisión de permisos `0005` en la base de destino; el despliegue no la aplica.
