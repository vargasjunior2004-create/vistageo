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
foto de fachada y coordenadas válidas. Antes de confirmar el registro se
muestran kardex, imagen y enlace Google Maps derivado de las coordenadas.
Las revisiones anteriores no se modifican. El servidor autoriza, valida,
audita y coordina las operaciones de Storage con PostgreSQL, incluyendo fallos
y reintentos.

### Consulta dinámica por kardex

La consulta busca automáticamente el texto literal escrito en cualquier parte
del kardex, sin distinguir mayúsculas y minúsculas y sin alterar los espacios
ni el identificador original. Kardex diferentes siguen siendo registros
distintos, incluso cuando coinciden al buscar. Se puede escribir el kardex
completo en el mismo campo. Se muestran coincidencias paginadas al desplazarse,
con fotografía si existe e identificación de la ubicación; al seleccionar una
se abre su ficha. La interfaz indica carga, ausencia de resultados y errores,
limita las solicitudes mientras se escribe y descarta respuestas obsoletas.
La consulta parcial y las fotografías requieren `ubicaciones.consultar`; la
consulta exacta necesaria para registrar conserva sus permisos actuales.

### Reemplazo de fotografía oficial

Desde la ficha de consulta se permite reemplazar una fotografía existente,
pero no agregar una primera fotografía ni modificar el kardex o el GPS. Se
requiere el permiso configurable `ubicaciones.fotografia.editar` y el acceso a
la consulta; los roles TECNICO, GERENTE, JEFE COMERCIAL, JEFE OPERATIVO,
JEFE TECNICO, CAJERO y CALL CENTER reciben inicialmente el permiso. El
permiso de consulta se asigna también a esos roles como requisito de acceso;
el administrador conserva acceso. El usuario toma o selecciona una imagen, la
previsualiza y confirma expresamente el reemplazo y la eliminación definitiva.

La imagen nueva se valida, optimiza, sube y verifica antes de publicar su
referencia. La operación es idempotente y serializada por ubicación; registra
actor, huellas anterior y nueva y progreso. La copia anterior de Storage,
incluidas copias de fotografías históricas, se elimina solo después de publicar
la nueva y de verificar que no sea una referencia vigente. Si la limpieza
falla, queda pendiente y se reintenta; no se informa como eliminada hasta
confirmarlo. El RAR original y los registros de procedencia no se modifican.
La fotografía anterior eliminada no puede recuperarse desde Storage; se
conserva su trazabilidad, no su contenido. Esta regla sustituye la decisión
anterior de conservar las fotos históricas en Storage.

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
Verificar también coincidencias parciales literales, mayúsculas y minúsculas,
paginación, permisos y descarte de respuestas anteriores en el buscador.
Para el reemplazo, verificar que no se alteran kardex ni GPS, la conservación
de procedencia, idempotencia, concurrencia, fallos y recuperación del borrado,
incluyendo reinicios y protección de referencias vigentes.
