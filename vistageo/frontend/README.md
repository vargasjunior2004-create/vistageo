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

Para servir frontend y API en un solo Web Service, usar el Dockerfile y las
instrucciones de [despliegue unificado](../backend/README.md#un-solo-web-service).
La aplicación se compila con `VITE_API_URL=/api`; no se debe configurar una
URL externa de API en ese build.

Como alternativa, con dos servicios:

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
- `npm test`: pruebas de calidad y validación de muestras GPS.

## Notas

- La identidad visual usa los tokens de color y los estilos compartidos de
  `src/index.css`; los iconos de navegación se implementan con Lucide React.
- Los placeholders reutilizables están en `src/components/Skeleton.tsx`:
  `Skeleton`, `SkeletonText`, `SkeletonCard`, `SkeletonTable`, `SkeletonAvatar`,
  `SkeletonImage` y `SkeletonDashboard`. Las pantallas muestran skeletons en la
  carga inicial; al actualizar, conservan los resultados existentes y mantienen
  visibles los estados de error y sin resultados. El shimmer respeta
  `prefers-reduced-motion`; la aplicación actualmente usa tema claro.
- El access token JWT se mantiene en memoria; el refresh token se guarda en
  `localStorage`. Al expirar el access token, el cliente intenta refrescar una
  vez; si la sesión ya no es válida, limpia la sesión y redirige al inicio.
- Las cuentas nuevas pueden acceder con su contraseña inicial y cambiarla
  opcionalmente desde el menú. Un restablecimiento administrativo sigue
  exigiendo cambiar la contraseña temporal.
- Las acciones deliberadas envían `X-Actividad-Usuario: true`.
- El frontend no sustituye la autorización del backend; todos los permisos se verifican en la API.
- Las notificaciones temporales usan Sonner: `notifications` en
  `src/services/notifications.ts` ofrece éxito, error, advertencia e información.
  Los mensajes idénticos del mismo tipo se agrupan mientras están visibles.
- La navegación lateral se adapta a móviles y puede contraerse en escritorio.
  Las opciones de trabajo se muestran según los permisos y roles existentes.
- El panel muestra registro y consulta de ubicaciones según sus permisos.
  La fotografía oficial y el GPS se guardan mediante el backend. Si falla la
  conexión, se conserva un borrador local por usuario para reintentar con la
  misma operación; descartarlo puede requerir revisión manual en el servidor.
- El registro ofrece cámara o archivo y exige elegir entre GPS del dispositivo
  y un enlace compartido; muestra un mapa y exige confirmar el punto. La
  fotografía sigue siendo obligatoria. El mapa incrustado de OpenStreetMap
  recibe las coordenadas para mostrar la vista previa y requiere conexión.
- Los diagnósticos de cámara se muestran en la consola con el prefijo
  `[GeoVista camera]` y se conservan en `localStorage` bajo
  `vistageo_camera_diagnostics` (máximo 100 eventos). Incluyen número de intento,
  cambios de visibilidad, tipo/tamaño de archivo y dimensiones procesadas; no
  almacenan imágenes, nombres ni URI. Una PWA no puede observar la URI ni el
  ciclo de vida nativo de Android; para investigar cierres del navegador se
  requieren registros del dispositivo.
  Los enlaces aceptados incluyen coordenadas puntuales de Google Maps y
  marcadores de OpenStreetMap; el servidor puede resolver enlaces cortos
  compatibles. La verificación automática de kardex es exacta
  y no requiere consultar contratos desde el formulario.
- La captura presencial busca durante un máximo de 30 segundos y conserva la
  mejor medición reciente; puede cancelarse o repetirse. Se muestra la precisión
  sin redondear y no se permiten nuevas capturas por encima del límite aceptable
  configurado en la API (20 m por defecto). Las mediciones sin confirmar caducan
  a los 30 segundos; al confirmar se detiene el GPS y se conserva el punto hasta
  guardarlo o iniciar otra búsqueda. Enlaces compartidos no tienen precisión ni
  hora de captura conocida.
  Los borradores antiguos sin precisión solo pueden reintentarse si el servidor
  ya recibió la operación; de lo contrario, descártalos y vuelve a capturar.
- Si un registro de campo quedó pendiente, el buscador y la comprobación
  exacta lo indican. El borrador original permite reintentar; si se perdió,
  hace falta revisión administrativa. Esto no identifica como pendientes las
  ubicaciones históricas que carecen de foto o coordenadas.
- Consultar ubicación busca automáticamente por una parte literal o por todo
  el kardex, sin distinguir mayúsculas y sin modificar espacios. Las
  coincidencias se cargan al desplazarse y cada una abre su ficha; la foto
  se solicita solo al abrir la ficha. Las respuestas de fotos usan `no-store`,
  por lo que volver a abrir una ficha vuelve a consultar su foto. Kardex que solo
  difieren por mayúsculas siguen siendo registros independientes; los
  espacios se muestran también con un marcador visible sin cambiar el kardex.
- Los resultados y la ficha muestran el usuario creador; la ficha muestra
  también la fecha de creación. Si no se conoce alguno de esos datos se indica
  como desconocido. El nombre mostrado es el nombre actual de la cuenta.
- Las herramientas administrativas de contratos y procedencia se conservan,
  pero no aparecen en el menú cotidiano.
- En la ficha se puede reemplazar una foto existente, actualizar el GPS o
  hacer ambos cambios con un motivo activo obligatorio y una observación
  opcional. Los permisos de foto y GPS se comprueban por separado y el
  historial textual es de solo lectura. Tras confirmar una foto, la copia anterior se elimina
  definitivamente, también si es histórica. Si falla la limpieza, se informa
  como pendiente; el borrador conserva la operación para reintentar desde el
  mismo dispositivo. El navegador no guarda las claves de Supabase.
- Los administradores, gerencia y jefe operativo pueden agregar, editar,
  activar y desactivar motivos. El permiso GPS se asigna expresamente
  desde Roles; no se concede automáticamente por tener permiso de fotografía.
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
  Las fotos seleccionadas admiten descripciones opcionales, conservadas solo
  mientras la página está abierta. Si hay descripciones, se envía un texto
  numerado en el orden de las fotos seleccionadas; la aplicación receptora puede
  omitir el texto o alterar la presentación, por lo que la correspondencia no
  puede garantizarse en todos los dispositivos.
- La cámara, GPS y service worker requieren HTTPS o localhost. El service worker
  solo se registra en producción y guarda recursos estáticos, no respuestas
  privadas de la API. Comprueba el funcionamiento offline en el dispositivo
  después de visitar la aplicación con conexión.
- Antes de habilitar las funciones en una base existente hay que revisar y
  autorizar por separado las revisiones pendientes hasta `0011`, según el
  estado de esa base; el despliegue no las aplica.
