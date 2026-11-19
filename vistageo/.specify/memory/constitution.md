<!--
Sync Impact Report
Version change: 1.0.0 -> 2.0.0
Modified principles: None.
Modified section: Restricciones de producto, datos y tecnología; FastAPI replaces
Django and Django REST Framework as the required backend framework.
Added sections: None.
Removed sections: None.
Follow-up TODO: Confirm the original ratification date.
Remove this report before committing the amended constitution.
-->

# VISTA GEO Constitution

## Core Principles

### I. Simplicidad operativa para técnicos
Cada flujo destinado al personal técnico MUST completar su objetivo con los
menos pasos, campos y datos manuales necesarios. La consulta por kardex MUST
ser directa, y los flujos de registro y actualización MUST priorizar captura
automática de fecha, hora y coordenadas cuando estén disponibles. La interfaz
MUST ser Mobile First, responsive y comprensible en teléfonos Android. No se
añadirán pasos o información sin una necesidad funcional aprobada.

### II. Autorización en el backend y protección de datos
El backend MUST aplicar autenticación, autorización basada en roles y
validación de propiedad en cada endpoint protegido. La interfaz MUST NOT ser
la única barrera de acceso. Las credenciales y fotografías MUST protegerse;
las claves administrativas y secretos de Supabase MUST NOT exponerse en el
frontend. Estas reglas reducen el riesgo de acceso o modificación no autorizados.

### III. Trazabilidad verificable
Las operaciones relevantes MUST registrar actor, fecha y hora, y conservar
los valores anteriores cuando se actualice una ubicación. Las ediciones
normales MUST NOT alterar ni sobrescribir silenciosamente el historial.
Las actividades MUST registrar inicio y finalización cuando corresponda, y
su duración MUST representar el trabajo realizado, no el tiempo que la
aplicación permanece abierta.

### IV. Arquitectura modular y responsabilidades claras
El producto MUST comenzar como un monolito modular con frontend y backend
separados. El backend será responsable de reglas de negocio, validaciones,
permisos, persistencia y API; el frontend será responsable de navegación,
formularios y presentación. La integración con GO VISTA MUST realizarse por
API REST y MUST NOT acoplar la implementación de ambos sistemas. No se
introducirán microservicios inicialmente.

### V. Especificación aprobada y cambios comprobables
No se implementará una funcionalidad hasta que su especificación haya sido
revisada y aprobada. Cada cambio MUST tener criterios de aceptación
verificables y pruebas acordes con su comportamiento. Las decisiones que
afecten arquitectura, datos o permisos MUST documentarse; ante ambigüedad
que afecte esos elementos, se solicitará una decisión antes de implementarlos.

## Restricciones de producto, datos y tecnología

- El stack principal es obligatorio: Python, FastAPI, API REST y
  documentación OpenAPI/Swagger en backend; React, TypeScript y
  Tailwind CSS en frontend; Supabase con PostgreSQL y Supabase Storage para
  fotografías. La configuración y las credenciales se obtendrán de variables
  de entorno. No se incorporará React Native ni se sustituirá este stack.
- El kardex será el único identificador para buscar clientes. No se crearán
  identificadores alternativos para representar al mismo cliente, y cada
  kardex podrá tener como máximo un registro de ubicación asociado.
- El control de acceso inicial contemplará Administrador, Jefa operativa,
  Jefe técnico, Técnico y Técnico eventual. Los permisos serán configurables
  y se verificarán en el backend.
- La sincronización sin conectividad MUST evitar duplicados e informar el
  estado de los registros pendientes. No se implementará una estrategia de
  sincronización compleja hasta que sus reglas estén definidas y aprobadas.
- La importación desde Dropbox MUST validar y previsualizar los datos,
  detectar duplicados e informar errores. No se ejecutarán migraciones reales
  sin autorización explícita.

## Flujo de desarrollo

- Specify será la metodología para organizar el trabajo. Antes de implementar
  cada funcionalidad, su especificación MUST describir objetivo, requisitos
  funcionales y no funcionales, reglas de negocio, modelo de datos, permisos,
  flujos de usuario, criterios de aceptación y pruebas necesarias.
- El desarrollo se dividirá en funcionalidades y tareas pequeñas. Las
  especificaciones y decisiones arquitectónicas se revisarán antes de generar
  implementación; la aprobación de una especificación no autoriza cambios
  ajenos a su alcance.
- Las pruebas MUST verificar los criterios de aceptación y los permisos
  aplicables. Los cambios de datos MUST conservar el historial y no podrán
  ejecutar operaciones destructivas sin autorización.
- Las decisiones técnicas relevantes y sus razones MUST quedar documentadas.
  Los requisitos no confirmados no se asumirán como hechos: se presentarán
  para decisión antes de afectar el diseño o el comportamiento.

## Governance

Esta constitución prevalece para las decisiones de producto y desarrollo de
VISTA GEO. Toda propuesta de enmienda MUST documentar su motivo, alcance e
impacto y contar con aprobación del responsable del proyecto antes de
adoptarse. Las versiones seguirán SemVer: MAJOR para cambios incompatibles
en principios o reglas, MINOR para principios o secciones nuevos o ampliados,
y PATCH para aclaraciones sin cambio de significado. Las especificaciones y
revisiones de cambios MUST comprobar su conformidad; cualquier excepción
requerirá justificación y aprobación documentadas.

**Version**: 2.0.0 | **Ratified**: TODO(RATIFICATION_DATE): fecha original de adopción pendiente de confirmar | **Last Amended**: 2026-11-18
