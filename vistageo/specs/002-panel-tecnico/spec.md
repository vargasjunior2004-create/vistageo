# Panel de trabajo VISTA GEO

## Alcance aprobado

El panel móvil ofrece registro y consulta de ubicaciones oficiales y una
cámara y galería independientes para fotos de jornada. Conserva la API,
modelos y autorización existentes. La fotografía oficial se guarda en el
bucket privado y se vincula con la ubicación; las fotos de jornada solo se
guardan localmente y nunca se envían automáticamente.

## Roles y permisos

Administrador, gerente, jefe comercial, técnico, cajero y call center pueden
tener acceso a las funciones de ubicación mediante permisos configurables del
RBAC existente. La preparación de permisos no autoriza ejecutar migraciones
ni modificar roles de una base real. Administrador, gerente y jefe comercial
pueden gestionar usuarios con los permisos existentes, que incluyen crear,
editar, desactivar y restablecer contraseñas. El técnico no debe ver funciones
administrativas.

## Ubicaciones

El kardex se conserva exactamente. Se permite crear el contrato cuando no
existe; si ya tiene una ubicación se rechaza el registro duplicado. Se requiere
foto de fachada y coordenadas válidas. Las fotos y revisiones anteriores no
se sobrescriben. El servidor autoriza, valida, audita y coordina las operaciones
de Storage con PostgreSQL, incluyendo fallos y reintentos.

## Jornada local y conectividad

Las imágenes de jornada se capturan, consultan, seleccionan, eliminan y
comparten desde el dispositivo, sin registrar imágenes en el servidor.
El usuario inicia el selector nativo; la elección de WhatsApp, destinatario y
confirmación son manuales. La transmisión requiere conexión y depende del
dispositivo. La interfaz local puede abrirse sin conexión ni nueva
autenticación después de su preparación inicial; en dispositivos compartidos
esto no protege las imágenes de otras personas con acceso al navegador.
La verificación y revocación del servidor no son posibles sin conectividad.
El almacenamiento web puede borrarse al limpiar datos del sitio o por límites
del navegador y no equivale necesariamente a la galería del sistema.

## Pruebas

Verificar autorizaciones por API, kardex exactos y duplicados, recuperación
de fallos de Storage, auditoría, captura y errores de GPS, persistencia y
borrado local, selector de compartir, funcionamiento sin conexión tras la
preparación inicial y ausencia de cargas de fotos de jornada. Utilizar
servicios simulados y PostgreSQL desechable; nunca datos de producción.
