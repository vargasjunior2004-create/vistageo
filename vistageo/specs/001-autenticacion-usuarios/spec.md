# Feature Specification: Autenticación y usuarios

**Feature Branch**: No creada

**Created**: 2026-11-18

**Status**: Aprobada por el usuario para desarrollar el módulo de usuarios y roles

**Input**: Autenticación y gestión de usuarios independientes de GO VISTA para
GEO VISTA, con simplicidad para el personal técnico.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Iniciar y cerrar sesión (Priority: P1)

Una persona con una cuenta activa inicia sesión con su nombre de usuario y
contraseña, accede a las funciones permitidas por su rol y cierra sesión al
terminar. La experiencia debe ser sencilla desde un teléfono.

**Why this priority**: El acceso autenticado es necesario para proteger las
funciones y atribuir acciones a una persona.

**Independent Test**: Con una cuenta activa y otra desactivada, verificar el
inicio de sesión, el rechazo de credenciales incorrectas, la protección de
acceso y el cierre de sesión.

**Acceptance Scenarios**:

1. **Given** una cuenta activa y sus credenciales correctas, **When** la
   persona inicia sesión, **Then** accede a su sesión y a las funciones que
   tenga autorizadas.
2. **Given** credenciales incorrectas, una cuenta inexistente o desactivada,
   **When** se intenta iniciar sesión, **Then** se rechaza el acceso con un
   mensaje que no identifica cuál de esos casos ocurrió.
3. **Given** un nombre de usuario y una contraseña introducidos con letras
   minúsculas o mixtas, **When** la persona los escribe y envía, **Then** ambos
   se convierten a mayúsculas; la contraseña permanece enmascarada y la
   verificación usa la forma convertida.
4. **Given** una sesión activa, **When** su titular cierra sesión, **Then**
   esa sesión ya no permite acceder a funciones protegidas.
5. **Given** una solicitud a una función protegida sin sesión válida o sin el
   permiso requerido, **When** se intenta acceder, **Then** se deniega el
   acceso aunque la interfaz muestre u oculte controles.
6. **Given** cinco intentos fallidos en una cuenta, **When** se intenta acceder
   durante los siguientes quince minutos, **Then** se rechaza el acceso aunque
   la contraseña sea correcta.

### User Story 2 - Proteger una sesión inactiva (Priority: P1)

El sistema cierra una sesión después de diez minutos sin actividad de su
titular para reducir el riesgo de uso no autorizado de un dispositivo.

**Why this priority**: Los técnicos pueden dejar temporalmente el teléfono
sin supervisión durante una visita.

**Independent Test**: Iniciar una sesión, medir su actividad y comprobar el
acceso antes y después del límite de inactividad.

**Acceptance Scenarios**:

1. **Given** una sesión válida, **When** se cumple el décimo minuto sin
   actividad del usuario, **Then** se rechaza el siguiente acceso protegido
   y se solicita iniciar sesión otra vez.
2. **Given** una sesión válida con menos de diez minutos de inactividad,
   **When** su titular realiza una acción autenticada, **Then** comienza un
   nuevo periodo de diez minutos para esa sesión.
3. **Given** una sesión inactiva, **When** solo ocurren comprobaciones
   automáticas o tareas en segundo plano, **Then** estas no prolongan la
   sesión.

### User Story 3 - Administrar cuentas (Priority: P2)

Una persona administradora crea, consulta, edita, activa y desactiva cuentas,
y asigna roles aprobados a las personas que trabajan en GEO VISTA.

**Why this priority**: El acceso es independiente de GO VISTA y debe
administrarse sin depender de ese sistema.

**Independent Test**: Con una cuenta administradora y otra no autorizada,
crear y desactivar una cuenta; comprobar que únicamente la administradora
puede realizar la operación y que la cuenta desactivada pierde acceso.

**Acceptance Scenarios**:

1. **Given** una persona administradora autorizada, **When** crea una cuenta
   con un nombre de usuario no utilizado y le asigna un rol aprobado, **Then**
   la cuenta queda disponible de acuerdo con su estado.
2. **Given** un nombre que coincide con otro después de convertirlo a
   mayúsculas, **When** se intenta crear o renombrar una cuenta, **Then** se
   rechaza la duplicación.
3. **Given** una cuenta activa con sesiones abiertas, **When** una persona
   administradora la desactiva, **Then** se bloquean sus sesiones y futuros
   inicios de sesión hasta que se reactive.
4. **Given** una persona sin permiso para administrar usuarios, **When**
   intenta crear, editar, activar, desactivar o asignar roles, **Then** el
   sistema rechaza la operación.
5. **Given** el despliegue inicial autorizado, **When** se prepara la primera
   cuenta administrativa, **Then** se identifica como `JUNIOR` y recibe el
   rol de administrador de sistemas sin incorporar una contraseña al código
   ni a la documentación.

### User Story 4 - Recuperar o cambiar la contraseña (Priority: P2)

Una persona puede cambiar su contraseña con su contraseña actual. Si la
olvida, solicita a una persona administradora que la restablezca.

**Why this priority**: Permite recuperar acceso sin integrar las cuentas con
GO VISTA y sin depender de un servicio de correo.

**Independent Test**: Cambiar una contraseña con la actual, restablecerla
mediante una persona administradora y comprobar las credenciales anteriores
y las nuevas.

**Acceptance Scenarios**:

1. **Given** una sesión válida y la contraseña actual correcta, **When** su
   titular establece una nueva contraseña, **Then** la anterior deja de ser
   válida y la nueva se verifica tras convertirla a mayúsculas.
2. **Given** una solicitud de recuperación verificada por una persona
   administradora, **When** esta restablece la contraseña por el procedimiento
   aprobado, **Then** la anterior y las sesiones existentes dejan de ser válidas
   y la persona debe cambiar la contraseña temporal al iniciar sesión.
3. **Given** una persona no autorizada para administrar usuarios, **When**
   intenta restablecer la contraseña de otra persona, **Then** el sistema
   rechaza la operación.

### Edge Cases

- Los campos vacíos no permiten iniciar sesión ni muestran información
  privada en el mensaje de error.
- La conversión a mayúsculas usa Unicode y no elimina espacios ni otros
  caracteres de la contraseña. La compatibilidad con la futura interfaz debe
  probarse antes de integrarla.
- Si la conectividad falla, se informa que no fue posible completar la
  operación; no se concede acceso sin verificación.
- Si una sesión caduca mientras se realiza una operación protegida, se
  rechaza la solicitud y se solicita iniciar sesión de nuevo; no se informa
  éxito para una operación no confirmada.
- Un restablecimiento no debe revelar ni recuperar la contraseña anterior.
- «Jefe operativo» y «jefa operativa» se refieren al mismo rol; su nombre
  definitivo es «Jefe operativo». El rol comercial sigue la misma regla y
  conserva el nombre «Jefe comercial».

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST autenticar cuentas propias de GEO VISTA
  mediante nombre de usuario y contraseña, sin requerir una cuenta GO VISTA.
- **FR-002**: El formulario MUST convertir a mayúsculas ambos campos y
  mantener la contraseña enmascarada.
- **FR-003**: El sistema MUST aplicar la conversión a mayúsculas en la
  verificación de credenciales y en la creación, cambio y restablecimiento
  de contraseñas, independientemente de la interfaz utilizada.
- **FR-004**: El sistema MUST impedir nombres de usuario duplicados tras
  convertirlos a mayúsculas.
- **FR-005**: El sistema MUST rechazar el inicio de sesión de cuentas
  desactivadas, inexistentes o con credenciales incorrectas, sin distinguir
  esos casos en el mensaje visible.
- **FR-006**: El sistema MUST permitir cerrar una sesión y rechazar su uso
  posterior para acceder a funciones protegidas.
- **FR-007**: El sistema MUST invalidar una sesión al cumplirse diez minutos
  sin actividad de su titular; procesos automáticos no cuentan como actividad.
- **FR-008**: El sistema MUST comprobar la sesión y los permisos para cada
  acceso protegido, sin depender únicamente de controles visuales.
- **FR-009**: Una persona administradora autorizada MUST poder crear,
  consultar, editar, activar y desactivar cuentas y asignar roles aprobados.
- **FR-010**: Al desactivar una cuenta, el sistema MUST bloquear sus sesiones
  existentes y rechazar nuevos inicios de sesión.
- **FR-011**: Una persona autenticada MUST poder cambiar su propia contraseña
  tras verificar la contraseña actual.
- **FR-012**: Una persona que haya olvidado su contraseña MUST poder solicitar
  su restablecimiento a una persona administradora autorizada.
- **FR-013**: El restablecimiento MUST invalidar la contraseña anterior y
  todas las sesiones existentes de la cuenta afectada.
- **FR-014**: El sistema MUST prever la cuenta inicial `JUNIOR` con el rol de
  administrador de sistemas; su creación y asignación de contraseña requieren
  autorización posterior y un procedimiento seguro.
- **FR-015**: El sistema MUST registrar los eventos de inicio de sesión,
  cierre de sesión, desactivación, cambio y restablecimiento de contraseña,
  con fecha y actor cuando se conozca, sin registrar contraseñas.
- **FR-016**: El sistema MUST mostrar mensajes comprensibles ante fallas de
  conectividad y MUST NOT presentar como exitosas operaciones no confirmadas.
- **FR-017**: Cada usuario MUST tener exactamente un rol.
- **FR-018**: Administrador, gerente, jefe comercial y jefe operativo MUST
  poder configurar los permisos de los roles; solo administrador puede
  modificar o asignar el rol administrador.
- **FR-019**: Las contraseñas MUST tener al menos ocho caracteres después
  de convertirse a mayúsculas y usar la conversión Unicode.
- **FR-020**: El restablecimiento MUST establecer una contraseña temporal y
  exigir su cambio al siguiente inicio de sesión.

### Non-Functional Requirements

- **NFR-001**: Las credenciales MUST protegerse; las contraseñas no se
  guardarán ni registrarán en texto claro y no se incluirán en código ni
  documentación.
- **NFR-002**: El inicio de sesión y los mensajes de error MUST ser utilizables
  en teléfonos Android y adaptarse a pantallas de distintos tamaños.
- **NFR-003**: El sistema MUST bloquear la cuenta durante quince minutos
  tras cinco intentos fallidos.
- **NFR-004**: Los eventos de auditoría MUST conservarse si una cuenta se
  desactiva; el periodo de retención queda pendiente de definición.

### Key Entities *(include if feature involves data)*

- **Usuario**: cuenta independiente con nombre de usuario, credencial
  protegida, estado y un rol aprobado; no es un cliente ni un kardex.
- **Rol y permiso**: conjunto configurable de autorizaciones; la matriz
  completa de funcionalidades distintas de este módulo sigue pendiente.
- **Sesión**: acceso de un usuario, con estado válido o inválido y momento
  de última actividad relevante.
- **Evento de auditoría**: acción, fecha y actor cuando se conoce, sin
  contraseñas ni información secreta.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En pruebas de aceptación, el 100 % de los accesos con
  credenciales incorrectas, cuentas desactivadas o sesiones cerradas son
  rechazados.
- **SC-002**: En pruebas de aceptación, el 100 % de las sesiones sin actividad
  durante diez minutos deja de permitir acciones protegidas; la actividad
  automática no prolonga ese periodo.
- **SC-003**: En pruebas de aceptación, el 100 % de los intentos de crear o
  renombrar usuarios que produzcan el mismo nombre en mayúsculas se rechaza.
- **SC-004**: En pruebas de aceptación, el 100 % de los cambios y
  restablecimientos comprobados invalida la contraseña anterior; los
  restablecimientos también invalidan las sesiones existentes.
- **SC-005**: En pruebas de aceptación, el 100 % de las operaciones
  administrativas intentadas por usuarios no autorizados se rechaza y el
  100 % de los eventos exigidos queda registrado sin contraseñas.

## Assumptions

- La actividad que renueva una sesión es una acción deliberada y autenticada
  de su titular; no incluye sondeos automáticos. Esta definición se presenta
  para revisión.
- La asignación de roles requiere una lista aprobada; cada usuario tiene un
  rol y la matriz completa de otras funcionalidades queda pendiente.
- Se requiere conectividad para verificar credenciales y permisos; no se
  define acceso sin conexión en esta funcionalidad.
- La identidad de la persona y la entrega segura de la contraseña temporal
  se verifican fuera de la API. El procedimiento operativo concreto y la
  recuperación si la única cuenta administradora queda inaccesible siguen
  pendientes.
- La conversión obligatoria de contraseñas a mayúsculas reduce las
  combinaciones posibles; se recomienda utilizar frases largas y únicas.
- El usuario autorizó desarrollar el módulo y crear tablas efímeras para
  pruebas aisladas. No autorizó crear usuarios reales ni ejecutar migraciones.
