# GEO VISTA — Plan de seguridad y estado de implementación

> **Propósito:** este documento conserva la auditoría, las decisiones ya
> autorizadas y el plan exacto de implementación para poder retomarlo sin
> depender del contexto de una conversación.
>
> **Estado actual:** auditoría terminada. **Fase 0, Fase 1, y parte de Fase 2/3
> implementadas en código y validadas con pruebas.** Pendientes: aplicar migración
> `0012` en PostgreSQL real, validación productiva/proxy/WAF, pruebas PostgreSQL
> con `TEST_DATABASE_URL`, y revisión operativa final. Este documento se actualiza
> con evidencia real.

Fecha de auditoría: 2026-11-25
Repositorio: `/home/junior/vistaGeo/vistageo`
Backend: FastAPI + SQLAlchemy + Alembic + PostgreSQL/Supabase
Frontend: React 19 + TypeScript + Vite

---

## 1. Resumen ejecutivo

La aplicación ya tenía una base de seguridad mejor de lo que sugería el
planteamiento inicial. **No usaba Django REST Framework ni JWT** (estado inicial
de la auditoría): usaba tokens Bearer opacos, aleatorios y revocables, con hash
en PostgreSQL. Desde Fase 1 se usa un modelo híbrido: JWT de acceso corto +
refresh opaco rotativo, manteniendo revocación en PostgreSQL.

Estado frente al objetivo (ver 1.1 para detalle):

1. [x] Migrar el token de acceso a **JWT de 15 minutos** sin perder revocación.
2. [x] Añadir **refresh token opaco de 7 días con rotación y detección de reuso**.
3. [x] Añadir **expiración absoluta** de sesión.
4. [x] Cerrar dos vulnerabilidades confirmadas de autorización:
   - autoascenso de rol;
   - auto-restablecimiento de contraseña sin conocer la actual.
5. [~] Endurecer login contra fuerza bruta distribuida (rate limit en memoria
   implementado; falta limitación distribuida/WAF en despliegue).
6. [~] Añadir cabeceras de seguridad, HTTPS/TrustedHost y desactivar docs en
   producción (implementado por configuración; falta validación productiva).
7. [~] Añadir pruebas de regresión para todos los mecanismos nuevos (cobertura
   principal agregada; faltan pruebas PostgreSQL reales y casos de despliegue).

**Decisiones ya autorizadas por el usuario:**

| Decisión | Opción elegida |
|---|---|
| Autenticación | Híbrido: JWT de acceso + refresh opaco rotativo con sesión en PostgreSQL |
| Roles | Solo `ADMINISTRADOR` asigna/cambia roles; nadie se autoedita rol/estado; nadie se auto-restablece la contraseña por endpoint administrativo |
| Alcance de ubicaciones/fotos | Global por permiso, como el `spec 002` actual |
| Migración | Autorizada migración Alembic `0012` **aditiva y no destructiva** |

## 1.1 Estado de implementación (actualizado)

### Validación ejecutada

- Backend: `cd backend && .venv/bin/python -m pytest -q --basetemp=/tmp/vistageo-pytest-01989a82` → **113 passed, 24 skipped, 1 warning** (2026-11-25).
- Frontend: `cd frontend && npm test` → **6 passed, 0 failed**.
- Frontend: `cd frontend && npm run build -- --outDir /tmp/vistageo-frontend-build` → **OK**. Se usó un directorio temporal porque `frontend/dist` ya contiene archivos propiedad de root.
- Las 24 pruebas omitidas son PostgreSQL (`TEST_DATABASE_URL` no configurado).

### Fase 0 — completada

Archivo: `backend/app/main.py`

1. **`POST /usuarios` (`create_user`)**: exige `require_admin(actor)`. Solo
   administrador crea usuarios/asigna roles.
2. **`PATCH /usuarios/{user_id}` (`edit_user`)**: bloquea autoedición de
   `role_id`/`active` con `403`; cambio de rol de terceros exige
   `require_admin(actor)`.
3. **`POST /usuarios/{user_id}/restablecer-contrasena` (`reset_password`)**:
   auto-reset bloqueado con `403` indicando `/auth/password`.
4. **`PUT /roles/{role_id}/permisos` (`set_permissions`)**: no-admin no puede
   modificar permisos de su propio rol (`403`).

Pruebas de regresión agregadas en `backend/tests/test_api.py`:
`test_user_cannot_self_escalate_role`, `test_user_cannot_self_deactivate`,
`test_user_cannot_self_reset_password`,
`test_only_admin_can_assign_roles_on_create`,
`test_only_admin_can_change_role`,
`test_non_admin_cannot_modify_own_role_permissions`, y ajuste de
`test_cannot_deactivate_last_administrator`.

### Fase 1 — núcleo implementado

#### Dependencias y configuración

- `backend/pyproject.toml`: agrega `PyJWT>=2.9,<3`.
- `backend/tests/conftest.py`: define `JWT_SECRET`, `JWT_ISSUER`,
  `JWT_AUDIENCE` de prueba.

#### Nuevo módulo de tokens

- `backend/app/tokens.py`: `TokenError`, `AccessClaims`, configuración por env
  (`JWT_SECRET`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_MINUTES`,
  `REFRESH_TOKEN_DAYS`, `SESSION_ABSOLUTE_HOURS`, `SESSION_IDLE_MINUTES`),
  `create_access_token`, `decode_access_token`, `generate_refresh_token`,
  `hash_refresh_token`, `looks_like_jwt`.

#### Modelo y migración

- `backend/app/models.py` (`AuthSession`): agrega `creado_en`, `expira_en`,
  `refresh_hash` (único), `refresh_expira_en`, `refresh_anterior_hash`,
  `refresh_generacion`, `revocada_en`, `revocada_motivo`.
- `backend/alembic/versions/0012_session_tokens.py`: migración **aditiva**; no
  elimina columnas; backfill de `creado_en/expira_en/refresh_generacion`; índice
  en `refresh_anterior_hash`; `downgrade()` bloqueado. **No aplicada en
  producción desde este entorno.**

#### Seguridad / autenticación

- `backend/app/security.py`: acepta JWT (`sid/sub`) y token opaco legado
  (`token_hash`); valida revocación, usuario activo, expiración absoluta,
  inactividad; marca `revocada_en/revocada_motivo`; helpers
  `revoke_session`/`revoke_all_sessions`.
- La autenticación normal y `POST /auth/refresh` aplican el mismo
  `SESSION_IDLE_MINUTES`; prueba de regresión añadida para verificar un límite
  configurado distinto de 10 minutos.
- `backend/app/main.py`:
  - `POST /auth/login`: devuelve `access_token` JWT, `refresh_token` opaco,
    `token_type`, `expires_in`, `must_change_password`; persiste sesión con
    expiración absoluta y refresh hasheado.
  - `POST /auth/refresh`: rota refresh, detecta reuso por
    `refresh_anterior_hash`, revoca todas las sesiones del usuario ante reuso,
    audita `RENOVAR_SESION` / `REUTILIZACION_REFRESH` / `SESION_VENCIDA`.
  - `POST /auth/logout`: revoca sesión actual con motivo.
  - `GET /auth/sessions`: lista sesiones propias activas.
  - `DELETE /auth/sessions/{id}`: revoca sesión propia; `404` si no es propia.
  - `DELETE /auth/sessions`: revoca todas las sesiones propias.
  - `POST /usuarios/{id}/revocar-sesiones`: admin/gestor autorizado revoca
    sesiones de usuario, con `protect_privileged_roles`.
  - `revoke_sessions` local ahora delega a `revoke_all_sessions` con motivo.

#### Schemas

- `backend/app/schemas.py`: agrega `RefreshRequest` y `SessionRead`.

#### Frontend

- `frontend/src/api/client.ts`: access token en memoria; refresh token en
  `localStorage` (`vistageo_refresh_token`); refresh automático en `401` con
  deduplicación; reintento único; limpieza y evento
  `vistageo:session-expired`; compatibilidad con token legado.
- `frontend/src/auth/AuthContext.tsx`: login guarda ambos tokens; init intenta
  refresh si hay refresh token; logout intenta `/auth/logout` y limpia sesión.
- `frontend/src/pages/ChangePasswordPage.tsx`: ya limpiaba sesión al éxito;
  compatible con el nuevo flujo.

#### Pruebas Fase 1

Archivo nuevo: `backend/tests/test_security_tokens.py` (16 pruebas):

- login devuelve JWT + refresh + expires.
- `/auth/me` acepta JWT.
- JWT expirado rechazado.
- JWT alterado rechazado.
- sesión revocada rechaza JWT.
- refresh rota tokens.
- reuso de refresh revoca sesión y bloquea refresh nuevo.
- refresh expirado rechazado.
- refresh de usuario desactivado rechazado.
- logout revoca refresh.
- borrar todas las sesiones revoca refresh.
- borrar sesión ajena devuelve 404.
- expiración absoluta rechaza sesión.
- token opaco legado sigue funcionando.
- contraseña temporal: `/auth/me` permitido con flag, rutas protegidas 403,
  `/auth/password` 204.
- admin puede revocar sesiones de usuario.

### Fase 2 — endurecimiento implementado (parcial)

- `backend/app/rate_limit.py`: rate limit en memoria por IP y por cuenta para
  `/auth/login`, configurable con `LOGIN_RATE_LIMIT_IP`,
  `LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS`, `LOGIN_RATE_LIMIT_ACCOUNT`,
  `LOGIN_RATE_LIMIT_ACCOUNT_WINDOW_SECONDS`. Responde `429` con `Retry-After`.
  **Limitación:** en memoria por proceso; en múltiples réplicas requiere WAF/proxy
  o store compartido.
- `backend/app/main.py`: `TRUSTED_HOSTS` (`TrustedHostMiddleware`), redirección
  HTTPS opcional (`FORCE_HTTPS`), HSTS opcional (`HSTS_ENABLED`), cabeceras de
  seguridad (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, `Cross-Origin-Opener-Policy`,
  `Cross-Origin-Resource-Policy`, `Content-Security-Policy`), límite por
  `Content-Length` (`MAX_REQUEST_BODY_BYTES`), docs deshabilitadas por defecto
  (`VISTAGEO_EXPOSE_DOCS=false`), endpoint `/health` sin auth.
- `backend/tests/test_security_tokens.py`: prueba de rate limit login (429).
- `backend/tests/test_api.py`: pruebas ajustadas para docs deshabilitadas por
  defecto y health endpoint en app unificada.

### Fase 3 / operación — implementado (parcial)

- `backend/app/database.py`: `DB_CONNECT_TIMEOUT_SECONDS`,
  `DB_STATEMENT_TIMEOUT_MS`, `DB_SSLMODE`, `DB_SSLROOTCERT`.
- `Dockerfile`: usuario no-root, `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`,
  `HEALTHCHECK` a `/api/health`, base `python:3.13-slim-bookworm`.
- `.github/workflows/ci.yml`: CI con backend tests, `pip-audit`, `bandit`,
  frontend test/build y `npm audit --omit=dev --audit-level=high`.
- `backend/.env.example`, `frontend/.env.example`: variables de configuración y
  seguridad documentadas sin secretos.
- `backend/README.md`, `frontend/README.md`: actualizados para JWT/refresh,
  endpoints de sesión, docs deshabilitadas por defecto, vars de seguridad y
  manejo de tokens en frontend.

### Pendiente / no hecho

- [ ] Aplicar migración `0012` en PostgreSQL desechable/producción con respaldo
  y autorización operativa.
- [ ] Regenerar `backend/sql/esquema_postgresql.sql` tras validar migración.
- [ ] Prueba contra PostgreSQL real con `TEST_DATABASE_URL`.
- [ ] Validación productiva: TLS real, proxy confiable, `TRUST_PROXY_HEADERS`,
  `FORCE_HTTPS`, `TRUSTED_HOSTS`, secretos, backups, monitoreo, Render.
- [ ] Rate limiting distribuido (Redis/WAF/proxy) para múltiples réplicas.
- [ ] Revisar CSP frente a recursos reales del frontend/despliegue; ajustar si
  hay orígenes externos necesarios.
- [ ] Fijar imágenes Docker por digest en pipeline de despliegue.
- [ ] Revisión de dependencias/SAST en CI con política de triage (permitir
  excepciones justificadas, no ignorar silenciosamente).
- [ ] Evaluar mover refresh token a cookie HttpOnly+Secure+SameSite en una fase
  posterior (cambio mayor de contrato/frontend).

### Handoff para siguiente agente

**Contexto rápido**
- Fase 0, 1 y parte de 2/3 ya están implementadas. No rehacer lo ya hecho.
- Cambios sensibles ya decididos: JWT híbrido con revocación en PostgreSQL; solo
  ADMIN asigna/cambia roles; nadie se autoedita rol/estado ni se auto-restablece
  por endpoint admin; alcance de ubicaciones/fotos global por permiso.
- No ejecutar migraciones destructivas, no `alembic downgrade`, no tocar datos
  de producción sin respaldo y autorización explícita.

**Validación actual**
```sh
cd backend && .venv/bin/python -m pytest -q   # 112 passed, 24 skipped, 1 warning
cd frontend && npm test                        # 6 passed
cd frontend && npm run build                   # OK
```

**Siguiente trabajo recomendado (en orden)**
1. **DB/migración (requiere autorización):** en PostgreSQL desechable con
   respaldo, aplicar `backend/alembic/versions/0012_session_tokens.py`, correr
   `TEST_DATABASE_URL=... .venv/bin/python -m pytest -q tests/test_postgresql_schema.py`,
   luego regenerar `backend/sql/esquema_postgresql.sql` con el flujo del README
   de backend. No aplicar en producción sin ventana/autorización.
2. **Configuración productiva:** definir `JWT_SECRET` fuerte (>=32 chars),
   `TRUSTED_HOSTS`, `CORS_ORIGINS`, `FORCE_HTTPS=true`, `HSTS_ENABLED=true`,
   `TRUST_PROXY_HEADERS=true` solo detrás de proxy confiable,
   `VISTAGEO_EXPOSE_DOCS=false`, `DB_SSLMODE`/certificado, y rate limits según
   tráfico. Ver `backend/.env.example`.
3. **Validación de despliegue:** confirmar que proxy/WAF/TLS envían headers
   esperados, que `/api/health` responde, que docs no estén expuestas, y que
   login/refresh/logout/revocación funcionen en entorno real.
4. **Endurecimiento restante:** rate limiting distribuido para múltiples
   réplicas; revisar CSP con recursos reales; fijar digests de imágenes Docker;
   triage de hallazgos de `pip-audit`/`bandit`/`npm audit` en CI.
5. **Tras cada cambio:** correr pruebas, actualizar `README_SEGURIDAD.md` con
   evidencia (fecha, comandos, resultado, archivos, riesgos).

**Archivos clave**
- `README_SEGURIDAD.md` — fuente de verdad.
- `backend/app/main.py` — endpoints auth/sesiones, rate limit, headers/docs.
- `backend/app/security.py`, `backend/app/tokens.py` — JWT/sesiones/revocación.
- `backend/app/rate_limit.py` — limitador en memoria.
- `backend/app/database.py` — timeouts/TLS DB.
- `backend/alembic/versions/0012_session_tokens.py` — migración aditiva, no aplicada.
- `frontend/src/api/client.ts`, `frontend/src/auth/AuthContext.tsx` — refresh/reintento/sesión.
- `Dockerfile`, `.github/workflows/ci.yml`, `backend/.env.example`, `frontend/.env.example`.

---

## 2. Correcciones importantes sobre supuestos

- **Autenticación actual:** JWT de acceso corto + refresh opaco rotativo con
  sesión en PostgreSQL; tokens opacos legados aceptados por compatibilidad.
- **No hay Django ni DRF.** El backend es FastAPI.
- **No hay app Android en el repositorio.** No se puede auditar ni garantizar
  compatibilidad con un cliente que no está aquí. La API mantiene compatibilidad
  con `access_token` Bearer; clientes deben manejar `refresh_token`/`expires_in`.
- **No hay repositorio Git** en el directorio auditado. No se pudo revisar el
  historial de secretos.
- **CI agregado** en `.github/workflows/ci.yml`; requiere ejecución en GitHub
  para evidencia real.
- **No hay docker-compose** ni configuración PostgreSQL versionada.
- El backend usa **SQLite en memoria** para pruebas unitarias; las pruebas de
  esquema PostgreSQL se omiten si no existe `TEST_DATABASE_URL`.

---

## 3. Línea base de pruebas

Línea base de auditoría inicial (2026-11-25):

```sh
cd backend && .venv/bin/python -m pytest -q  # 89 passed, 24 skipped
cd frontend && npm test                       # 6 passed
```

Validación actual tras Fase 0/1/2/3 parcial (2026-11-25):

```sh
cd backend && .venv/bin/python -m pytest -q  # 112 passed, 24 skipped, 1 warning
cd frontend && npm test                       # 6 passed
cd frontend && npm run build                  # OK
```

> Las 24 pruebas omitidas son PostgreSQL y requieren `TEST_DATABASE_URL` apuntando
> a una base desechable con revisiones aplicadas.

---

## 4. Arquitectura actual verificada

### 4.1 Login y sesión

- Endpoint: `POST /auth/login` (`backend/app/main.py:123-149`).
- Contraseña: Argon2 (`backend/app/security.py:31-41`).
- Token: `secrets.token_urlsafe(32)` (256 bits).
- Persistencia: solo `sha256(token)` en `sesiones.token_hash`.
- Validación: `current_session` (`backend/app/security.py:63-92`).
- Inactividad: 10 minutos (`SESSION_IDLE`).
- Actividad: solo se prolonga con `X-Actividad-Usuario: true`.
- Logout: revoca la sesión actual (`main.py:162-167`).
- Desactivar cuenta: revoca todas las sesiones (`main.py:232-233`).
- Cambiar/restablecer contraseña: revoca todas las sesiones
  (`main.py:177-180`, `main.py:253-258`).

### 4.2 Roles

- Tablas: `roles`, `permisos`, `rol_permisos`.
- `ADMINISTRADOR` tiene bypass total.
- Roles oficiales: `ADMINISTRADOR`, `GERENCIA`, `JEFE OPERATIVO`,
  `JEFE TECNICO`, `TECNICO`.
- `require_permission` y `require_admin` se ejecutan en backend.
- Último administrador protegido (`main.py:110-120`).

### 4.3 Fotografías

- Bucket privado `fachada`.
- El backend descarga y sirve la imagen; la clave de Supabase nunca llega al
  navegador.
- Verificación SHA-256 antes de entregar.
- `Cache-Control: private, no-store`.
- `X-Content-Type-Options: nosniff`.
- Imágenes re-codificadas a WebP, máximo 8 MiB de entrada, 32 MP, sin
  animaciones, sin metadatos.

### 4.4 Auditoría

- `auditoria_usuarios` para cuentas/sesiones.
- `auditoria` para ubicaciones/fotos.
- Triggers de inmutabilidad.
- RLS y revocación de privilegios para roles Supabase (`0003`).

---

## 5. Hallazgos clasificados

| ID | Área | Estado | Riesgo | Evidencia |
|---|---|---|---|---|
| H01 | Stack | Correcto | — | FastAPI + SQLAlchemy |
| H02 | Login/Argon2 | Correcto | — | `security.py:31-41` |
| H03 | Token actual | Parcial | Medio | Opaco, no JWT |
| H04 | Refresh token | No implementado | Medio | No existe |
| H05 | Rotación/reuso | No implementado | Medio | No aplica al token actual |
| H06 | Logout actual | Correcto | — | `main.py:162-167` |
| H07 | Revocación por dispositivo | Parcial | Medio | No hay inventario/endpoint |
| H08 | Desactivar cuenta revoca | Correcto | — | `main.py:232-233` |
| H09 | Cambio/reset revoca | Correcto | — | `main.py:177-180`, `253-258` |
| H10 | Expiración absoluta | No implementado | **Alto** | `AuthSession` sin `expires_at` |
| H11 | RBAC backend | Correcto/Parcial | Medio | Controles inline |
| H12 | Autoascenso de rol | **Vulnerable** | **Alto** | Confirmado `200` |
| H13 | Auto-reset contraseña | **Vulnerable** | **Alto** | `main.py:246-260` |
| H14 | Último admin | Correcto | — | `main.py:110-120` |
| H15 | Asignación de roles gestores | Parcial | Medio | Sin comparación de permisos |
| H16 | Alcance de ubicaciones | Decisión de negocio | Medio | Global por `spec 002` |
| H17 | Validación GPS | Correcto | — | Pydantic + límites |
| H18 | Trazabilidad GPS | Correcto | — | Revisiones + auditoría |
| H19 | Fotos privadas | Correcto | — | Proxy + SHA-256 |
| H20 | Autorización de fotos | Correcto/Parcial | Medio | Permiso, sin alcance por dueño |
| H21 | Validación de archivos | Correcto | — | Pillow + re-encode |
| H22 | URLs firmadas | No implementado | Bajo | Se usa proxy |
| H23 | Kardex único | Correcto | — | PK textual |
| H24 | Hash contraseñas | Correcto | Bajo | Argon2 sin rehash |
| H25 | Política contraseñas | Parcial | Medio | Mínimo 8 + mayúsculas |
| H26 | Secretos/.env | Parcial | Bajo | `.env` ignorado; sin gestor |
| H27 | `SECRET_KEY` | No aplica | — | No hay JWT actualmente |
| H28 | Docs/`DEBUG` | Parcial | Medio | `/docs` y `/api/docs` públicos |
| H29 | `ALLOWED_HOSTS` | No implementado | Medio | Sin TrustedHost |
| H30 | CORS | Correcto | — | Orígenes explícitos |
| H31 | CSRF | Correcto/No aplica | — | Bearer, sin cookies |
| H32 | HTTPS | Parcial/No verificable | Medio | Depende del despliegue |
| H33 | Fuerza bruta | Parcial | **Alto/Medio** | Solo bloqueo por cuenta |
| H34 | Validación entrada | Correcto | — | Pydantic estricto |
| H35 | ORM/SQLi | Correcto | — | SQLAlchemy |
| H36 | Tamaño de body | No implementado | Medio | Límite se aplica tras parsear |
| H37 | Logs sin secretos | Correcto | — | Verificado por prueba |
| H38 | Auditoría | Parcial | Medio | Sin IP/UA, lecturas, 403 |
| H39 | Docker | Parcial | Medio/Bajo | Root, sin healthcheck |
| H40 | PostgreSQL/RLS | Correcto/Parcial | Medio | App como owner/BYPASSRLS |
| H41 | TLS PostgreSQL | Parcial | Medio | Solo Storage lo exige |
| H42 | Android | No verificable | — | No está en el repo |
| H43 | Fotos locales jornada | Vulnerable/Parcial | Medio | IndexedDB sin sesión |
| H44 | CI/SAST | No implementado | Bajo | Sin workflows |

---

## 6. Plan de implementación

### Fase 0 — Correcciones de autorización (sin migración)

**Objetivo:** cerrar H12, H13 y parte de H15 sin tocar el esquema.

#### 6.1 `backend/app/main.py` — `create_user`

- Mantener `require_permission(actor, "usuarios.gestionar")`.
- Añadir `require_admin(actor)` para asignar rol (decisión: solo admin asigna
  roles). Consecuencia: un gestor no administrador ya no crea usuarios, porque
  `role_id` es obligatorio. Documentarlo.
- Mantener `protect_privileged_roles`, catálogo oficial y auditoría.

#### 6.2 `backend/app/main.py` — `edit_user`

- Si `data.role_id` cambia, exigir `require_admin(actor)`.
- Si `user.id == actor.id` y se intenta cambiar `role_id` o `active`, devolver
  `403` con mensaje claro.
- El cambio de `username` propio puede permitirse; si se decide prohibirlo,
  comprobar también.
- Mantener `protect_privileged_roles` y `protect_last_admin`.
- Auditar antes/después.

#### 6.3 `backend/app/main.py` — `reset_password`

- Si `user.id == actor.id`, devolver `403`:
  `"Usa /auth/password para cambiar tu propia contraseña"`.
- Mantener `protect_privileged_roles`, revocación y auditoría.

#### 6.4 `backend/app/main.py` — `set_permissions`

- Si `role.id == actor.role_id` y el actor no es `ADMINISTRADOR`, devolver
  `403`: nadie modifica los permisos de su propio rol.
- Mantener la restricción actual para el rol administrador.

#### 6.5 Pruebas Fase 0

Añadir a `backend/tests/test_api.py` (o `test_security.py`):

1. `TECNICO` con `usuarios.gestionar` intenta `PATCH /usuarios/{self}` con
   `role_id` de `JEFE TECNICO` → `403`.
2. `ADMIN` cambia el rol de otro usuario → `200`.
3. Gestor no administrador intenta `POST /usuarios` con rol no privilegiado →
   `403`.
4. Cualquier usuario intenta `POST /usuarios/{self}/restablecer-contrasena` →
   `403`.
5. `ADMIN` restablece la contraseña de otro usuario → `204`.
6. `GERENCIA` intenta modificar permisos de su propio rol → `403`.
7. `ADMIN` modifica permisos de `GERENCIA` → `200`.

---

### Fase 1 — JWT + refresh rotativo + expiración absoluta

> Requiere migración `0012`. No aplicar en producción sin respaldo y
> autorización expresa de ventana.

#### 7.1 Dependencia

Añadir a `backend/pyproject.toml`:

```toml
"PyJWT>=2.9,<3",
```

#### 7.2 Nuevo módulo `backend/app/tokens.py`

Responsabilidades separadas de `security.py`:

```python
# Configuración
JWT_SECRET          # obligatorio, >= 32 caracteres
JWT_ISSUER          # por defecto "geo-vista"
JWT_AUDIENCE        # por defecto "geo-vista-api"
ACCESS_TOKEN_MINUTES # por defecto 15
REFRESH_TOKEN_DAYS   # por defecto 7
SESSION_ABSOLUTE_HOURS # por defecto 168 (7 días)
```

Funciones pequeñas:

- `jwt_secret() -> str` — lee y valida `JWT_SECRET`.
- `access_token_ttl() -> timedelta`.
- `refresh_token_ttl() -> timedelta`.
- `absolute_session_ttl() -> timedelta`.
- `create_access_token(session_id: int, user_id: int, now: datetime | None = None) -> tuple[str, int]`
  - Claims: `sub`, `sid`, `jti`, `iat`, `exp`, `iss`, `aud`, `typ="access"`.
  - Algoritmo: `HS256`.
- `decode_access_token(token: str) -> AccessClaims` — valida firma, `iss`,
  `aud`, `exp`, `iat`, `sub`, `sid`, `jti`, `typ`.
- `generate_refresh_token() -> str` — `secrets.token_urlsafe(32)`.
- `hash_refresh_token(token: str) -> str` — SHA-256 hex.
- `looks_like_jwt(token: str) -> bool` — exactamente dos puntos.

Errores: `TokenError` propia o `jwt.InvalidTokenError` capturada en
`security.py`.

**No** guardar el access token en la base. La firma y la consulta a la sesión
son la validación.

#### 7.3 Modelo `AuthSession` (`backend/app/models.py`)

Añadir columnas **nullable o con default** para no romper datos existentes:

| Columna | Tipo | Uso |
|---|---|---|
| `creado_en` | `DateTime(timezone=True)` | Inicio de sesión |
| `expira_en` | `DateTime(timezone=True)` | Expiración absoluta |
| `refresh_hash` | `String(64)` unique nullable | Hash del refresh actual |
| `refresh_expira_en` | `DateTime(timezone=True)` nullable | Expiración del refresh |
| `refresh_anterior_hash` | `String(64)` nullable | Detección de reuso |
| `refresh_generacion` | `Integer` default 0 | Contador de rotaciones |
| `revocada_en` | `DateTime(timezone=True)` nullable | Fecha de revocación |
| `revocada_motivo` | `String(80)` nullable | Motivo auditable |

Mantener `token_hash`, `last_activity`, `revoked` para compatibilidad con
sesiones antiguas.

#### 7.4 Migración `backend/alembic/versions/0012_session_tokens.py`

- `revision = "0012_session_tokens"`
- `down_revision = "0011_gps_quality"`
- Solo `op.add_column` y `create_index`/`UniqueConstraint`.
- Backfill seguro:
  - `creado_en = now()` para filas existentes.
  - `expira_en = now() + interval '7 days'` para filas existentes.
  - `refresh_generacion = 0`.
- No borrar ni renombrar columnas.
- `downgrade()` debe fallar con `RuntimeError` (política actual del proyecto)
  o ser explícitamente no destructivo. **No ejecutar downgrade.**
- Regenerar `backend/sql/esquema_postgresql.sql` solo después de autorización.

#### 7.5 `backend/app/security.py`

Refactorizar en funciones pequeñas:

- `_query_session_by_id(db, session_id)`.
- `_query_session_by_token_hash(db, token)` (compatibilidad legada).
- `_session_from_credentials(db, token) -> AuthSession`:
  - Si `looks_like_jwt(token)`: decodificar, buscar por `sid`, comprobar
    `sub == session.user_id`.
  - Si no: buscar por `token_hash` (tokens opacos antiguos).
- `_ensure_session_active(session, now)`:
  - `revoked` → 401.
  - usuario inactivo → 401.
  - `expira_en` vencido → revocar, auditar `SESION_VENCIDA`, 401.
  - inactividad `>= SESSION_IDLE` → revocar, auditar `SESION_VENCIDA`, 401.
- `_touch_session_if_needed(session, user_activity)`.
- `revoke_session(db, session, reason)`.
- `revoke_all_sessions(db, user_id, reason)`.
- `current_session` usa las funciones anteriores.
- `current_user` sin cambios.

Auditoría: no guardar tokens; solo `session.id`, `user_id`, motivo.

#### 7.6 `backend/app/main.py` — login

- Crear `AuthSession` con:
  - `token_hash` legado (puede mantenerse para compatibilidad, aunque el
    access sea JWT; útil si se quiere aceptar el token opaco).
  - `refresh_hash = hash_refresh_token(refresh_token)`.
  - `creado_en = now`.
  - `expira_en = now + absolute_session_ttl()`.
  - `refresh_expira_en = min(now + refresh_ttl(), expira_en)`.
  - `refresh_generacion = 0`.
- Generar access JWT con `session.id`.
- Respuesta:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaque>",
  "token_type": "bearer",
  "expires_in": 900,
  "must_change_password": false
}
```

Mantener `access_token`, `token_type` y `must_change_password` para no romper
clientes existentes.

#### 7.7 `POST /auth/refresh`

Schema `RefreshRequest`:

```json
{ "refresh_token": "<opaque>" }
```

Lógica:

1. `hash = hash_refresh_token(body.refresh_token)`.
2. Buscar sesión por `refresh_hash` con `FOR UPDATE`.
3. Si no existe, buscar por `refresh_anterior_hash`.
4. Si coincide con `refresh_anterior_hash` → **reuso**:
   - revocar todas las sesiones del usuario;
   - auditar `REUTILIZACION_REFRESH`;
   - devolver `401`.
5. Validar `revoked`, usuario activo, `refresh_expira_en`, `expira_en`,
   inactividad.
6. Rotar:
   - `refresh_anterior_hash = refresh_hash`;
   - `refresh_hash = hash(nuevo_refresh)`;
   - `refresh_generacion += 1`;
   - `refresh_expira_en = min(now + refresh_ttl(), expira_en)`.
7. Emitir nuevo access JWT.
8. Auditar `RENOVAR_SESION`.
9. Devolver `access_token`, `refresh_token`, `expires_in`.

El refresh **no** debe prolongar `last_activity`; la actividad deliberada se
sigue marcando con `X-Actividad-Usuario`.

#### 7.8 Endpoints de sesiones

- `GET /auth/sessions` → lista de sesiones propias:
  `id`, `creado_en`, `ultima_actividad`, `expira_en`, `actual`.
- `DELETE /auth/sessions/{id}` → revoca una sesión propia; `404` si no es
  propia; `204` si funciona.
- `DELETE /auth/sessions` → revoca todas las sesiones propias; `204`.
- `POST /usuarios/{id}/revocar-sesiones` → requiere
  `usuarios.gestionar`; aplica `protect_privileged_roles`; audita
  `REVOCAR_SESIONES_USUARIO`; `204`.

#### 7.9 Frontend

`frontend/src/api/client.ts`:

- Access token **en memoria** (`let accessToken`), no en `localStorage`.
- Refresh token en `localStorage` (`vistageo_refresh_token`). Documentar que
  sigue siendo accesible ante XSS; alternativa futura: cookie HttpOnly.
- `setTokens(access, refresh)`, `clearTokens()`, `getAccessToken()`.
- `apiFetch`:
  - añade Bearer;
  - si `401` y no es `/auth/login` ni `/auth/refresh`, intenta refresh una sola
    vez;
  - deduplica refreshes concurrentes con una promesa compartida;
  - si refresh falla, limpia tokens y emite `vistageo:session-expired`;
  - reintenta la petición original.
- `apiRequest` mantiene el contrato actual.

`frontend/src/auth/AuthContext.tsx`:

- `login` guarda `access_token` y `refresh_token`.
- Al iniciar, si hay refresh token, llama `/auth/refresh` y luego `/auth/me`.
- `logout` llama `/auth/logout`; si falla la red, limpia tokens igualmente.
- Al cambiar contraseña, limpia tokens (el backend revoca todas las sesiones).
- No romper `must_change_password`.

`frontend/src/pages/ChangePasswordPage.tsx`: revisar que tras `204` se limpien
tokens y se redirija al login.

#### 7.10 Compatibilidad

- Los tokens opacos ya emitidos siguen funcionando hasta su inactividad de 10
  minutos.
- Los clientes antiguos que solo lean `access_token` siguen funcionando.
- Los clientes nuevos usan `refresh_token`.
- No cambiar el nombre `access_token` ni el esquema `Bearer`.

#### 7.11 Pruebas Fase 1

Nuevo `backend/tests/test_security_tokens.py` (o ampliar `test_api.py`):

1. Login devuelve JWT con tres segmentos y refresh token.
2. `GET /auth/me` con access JWT → `200`.
3. Access JWT expirado → `401`.
4. Access JWT con firma alterada → `401`.
5. Access JWT de una sesión revocada → `401`.
6. Refresh válido rota y devuelve tokens nuevos.
7. Refresh anterior después de rotar → `401` y revoca la sesión.
8. Refresh expirado → `401`.
9. Refresh de usuario desactivado → `401`.
10. Logout revoca refresh; usarlo devuelve `401`.
11. `DELETE /auth/sessions` revoca todas.
12. `DELETE /auth/sessions/{id}` de otro usuario → `404`.
13. Expiración absoluta → `401` aunque haya actividad.
14. Token opaco legado sigue funcionando.
15. Contraseña temporal: solo `/auth/me`, `/auth/password`, `/auth/logout`
    (mantener comportamiento actual).

---

### Fase 2 — Fuerza bruta, cabeceras y configuración

#### 7.12 Rate limiting

Crear `backend/app/rate_limit.py`:

- Ventana deslizante en memoria, protegida por `threading.Lock`.
- Claves: IP (`request.client.host`) y usuario normalizado.
- Límites configurables:
  - `LOGIN_RATE_LIMIT_PER_MINUTE` (por IP, defecto 30).
  - `LOGIN_RATE_LIMIT_PER_USERNAME` (por usuario, defecto 10).
- Al exceder: `429` con `Retry-After`.
- Reset para pruebas: `reset_login_rate_limits()`.
- Documentar que en múltiples workers se necesita Redis/WAF; esto es defensa
  en profundidad, no la única capa.
- En `login`, llamar antes de verificar contraseña.
- No registrar el username completo en logs si se considera sensible; usar
  hash o el propio audit event.

#### 7.13 Cabeceras de seguridad

Crear `backend/app/security_headers.py` o middleware en `main.py`:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: geolocation=(self), camera=(self), microphone=()`
- `Content-Security-Policy` (frontend):
  - `default-src 'self'`
  - `script-src 'self'`
  - `style-src 'self' 'unsafe-inline'`
  - `img-src 'self' data: blob: https://*.tile.openstreetmap.org`
  - `frame-src https://www.openstreetmap.org`
  - `connect-src 'self'`
  - `object-src 'none'`
  - `base-uri 'self'`
  - `form-action 'self'`
  - `frame-ancestors 'none'`
- `Strict-Transport-Security` solo si `APP_ENV=production` y
  `HSTS_SECONDS>0`.
- Aplicar también al app unificado (`backend/app/unified.py`), no solo al API.

#### 7.14 TrustedHost y HTTPS

- `TrustedHostMiddleware` con `TRUSTED_HOSTS` separados por coma.
- Redirección HTTPS configurable (`HTTPS_REDIRECT=true`) detrás del proxy.
- Desactivar `/docs`, `/redoc`, `/openapi.json` si `DOCS_ENABLED=false`.
- En Docker: `uvicorn ... --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"`.

#### 7.15 Tamaño de body

- Añadir comprobación de `Content-Length` antes de procesar endpoints con
  base64 (por ejemplo, máximo 16 MB).
- Configurar límite en proxy/WAF.
- No confiar solo en Pydantic.

#### 7.16 Pruebas Fase 2

1. Sexto intento de login desde la misma IP → `429`.
2. Login correcto tras ventana → `200`.
3. Cabeceras presentes en API y frontend.
4. `/docs` y `/api/docs` → `404` con `DOCS_ENABLED=false`.
5. Host no permitido → `400`.
6. Body mayor al límite → `413`.

---

### Fase 3 — Infraestructura y operación

#### 7.17 Docker

- Crear usuario no root y `USER app`.
- Añadir `HEALTHCHECK`.
- Pinnear versiones/digests de imágenes base.
- No copiar `.env`.
- Mantener `VISTAGEO_PHOTO_CLEANUP_ENABLED=true`.

#### 7.18 PostgreSQL

- Validar `sslmode=verify-full` y `sslrootcert` al iniciar, no solo en
  `Storage`.
- Añadir `statement_timeout` y `lock_timeout` razonables.
- Documentar rol de aplicación con privilegios mínimos.
- Mantener RLS como defensa en profundidad; recordar que el owner/BYPASSRLS la
  elude.

#### 7.19 CI

Crear `.github/workflows/ci.yml`:

- `pytest`.
- `npm test`.
- `npm run lint`.
- `npm run build`.
- `pip-audit` o equivalente.
- Escaneo de secretos (gitleaks/trufflehog).
- Opcional: `bandit`/`semgrep`.

#### 7.20 Documentación

Actualizar `backend/README.md` y `frontend/README.md`:

- Nuevos endpoints.
- Variables de entorno.
- Rotación de refresh.
- Revocación.
- Limitaciones (localStorage, rate limit en memoria).
- Configuración de Render.
- Procedimiento de migración y respaldo.

---

## 8. Configuración de entorno propuesta

Añadir a `backend/.env.example` (nunca valores reales):

```dotenv
DATABASE_URL=postgresql+psycopg://...
SUPABASE_URL=https://<proyecto>.supabase.co
SUPABASE_SECRET_KEY=<secreto>
CORS_ORIGINS=https://app.example.com
APP_ENV=production
JWT_SECRET=<mínimo 32 caracteres aleatorios>
JWT_ISSUER=geo-vista
JWT_AUDIENCE=geo-vista-api
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=7
SESSION_ABSOLUTE_HOURS=168
SESSION_IDLE_MINUTES=10
TRUSTED_HOSTS=app.example.com
HTTPS_REDIRECT=true
HSTS_SECONDS=31536000
DOCS_ENABLED=false
LOGIN_RATE_LIMIT_PER_MINUTE=30
LOGIN_RATE_LIMIT_PER_USERNAME=10
FORWARDED_ALLOW_IPS=<IP del proxy>
```

Notas:

- `JWT_SECRET` no debe reutilizar `SUPABASE_SECRET_KEY` ni `DATABASE_URL`.
- En producción, usar el gestor de secretos del proveedor.
- No commitear `.env`.
- Si se usa el modo de dos servicios, configurar CORS exacto y HTTPS.

---

## 9. Contratos de API resultantes

### `POST /auth/login`

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<opaco>",
  "token_type": "bearer",
  "expires_in": 900,
  "must_change_password": false
}
```

### `POST /auth/refresh`

```json
{ "refresh_token": "<opaco>" }
```

Respuesta:

```json
{
  "access_token": "<jwt>",
  "refresh_token": "<nuevo opaco>",
  "token_type": "bearer",
  "expires_in": 900
}
```

### `POST /auth/logout`

- Sin cuerpo. Revoca la sesión actual.
- `204`.

### `GET /auth/sessions`

```json
[
  {
    "id": 12,
    "creado_en": "2026-11-25T10:00:00Z",
    "ultima_actividad": "2026-11-25T10:05:00Z",
    "expira_en": "2026-12-02T10:00:00Z",
    "actual": true
  }
]
```

### `DELETE /auth/sessions/{id}`

- `204` si es propia.
- `404` si no existe o no es propia.

### `DELETE /auth/sessions`

- `204`.

---

## 10. Orden de ejecución recomendado

1. **Crear rama/worktree** (si se habilita Git) y respaldo.
2. Fase 0 completa + pruebas. Ejecutar `pytest`.
3. Añadir `PyJWT` y `tokens.py` + pruebas unitarias de tokens.
4. Añadir migración `0012` y probarla en PostgreSQL desechable:
   ```sh
   TEST_DATABASE_URL=... .venv/bin/python -m pytest -q tests/test_postgresql_schema.py
   ```
5. Refactorizar `security.py` manteniendo tokens opacos legados.
6. Cambiar login, añadir refresh y sesiones.
7. Actualizar frontend.
8. Ejecutar pruebas backend y frontend.
9. Añadir rate limiting y cabeceras.
10. Endurecer Docker/PostgreSQL/CI.
11. Actualizar READMEs.
12. Desplegar primero backend compatible y luego frontend, o ambos a la vez.
13. Verificar en producción: login, refresh, logout, revocación, fotos, GPS.

---

## 11. Criterios de aceptación

- [ ] Un usuario sin token recibe `401`.
- [ ] Un access token expirado recibe `401`.
- [ ] Un access token de sesión revocada recibe `401`.
- [ ] Un refresh rotado no puede reutilizarse.
- [ ] La reutilización de refresh revoca la sesión y queda auditada.
- [ ] Logout invalida access y refresh.
- [ ] Desactivar cuenta invalida todas las sesiones.
- [ ] Cambiar/restablecer contraseña invalida todas las sesiones.
- [ ] La sesión tiene expiración absoluta.
- [ ] Un usuario no puede cambiar su propio rol/estado.
- [ ] Un usuario no puede restablecer su propia contraseña por endpoint admin.
- [ ] Solo `ADMINISTRADOR` asigna/cambia roles.
- [ ] Un gestor no modifica permisos de su propio rol.
- [ ] Los permisos se validan en backend en todos los endpoints sensibles.
- [ ] Las fotos siguen siendo privadas y verificadas por SHA-256.
- [ ] No se registran contraseñas, tokens ni claves en logs.
- [ ] `pytest` pasa completo.
- [ ] `npm test` y `npm run build` pasan.
- [ ] `/docs` deshabilitado en producción.
- [ ] Cabeceras de seguridad presentes.
- [ ] Rate limit de login activo.

---

## 12. Riesgos y limitaciones pendientes

1. **Refresh token en `localStorage`**: sigue expuesto a XSS. Mitigación
   futura: cookie `HttpOnly; Secure; SameSite=Strict` para web, manteniendo
   body para Android. Requiere CORS con credenciales y CSRF.
2. **Rate limit en memoria**: no se comparte entre workers. Usar Redis/WAF en
   producción.
3. **Alcance global**: decisión tomada; si cambia el requisito, requiere modelo
   de propietario/equipo y migración de datos.
4. **Fotos locales de jornada**: IndexedDB no está protegido por sesión.
   Evaluar cifrado local, PIN o limpieza al cerrar sesión.
5. **App Android**: no está en el repositorio; no se puede verificar.
6. **Producción**: TLS, WAF, backups y secretos reales no son verificables
   desde el código.
7. **Migración**: no aplicar sin respaldo, ventana y autorización.
8. **Token opaco legado**: se aceptará hasta que expire la sesión; no hay
   refresh para esas sesiones.
9. **Sin MFA** y sin historial de contraseñas; evaluar según criticidad.
10. **Bucket privado**: se verifica en importadores, no en cada lectura.

---

## 13. Archivos que se modificarán

### Backend

- `backend/pyproject.toml`
- `backend/app/tokens.py` (nuevo)
- `backend/app/security.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/rate_limit.py` (nuevo)
- `backend/app/security_headers.py` (nuevo o middleware en `main.py`)
- `backend/app/unified.py`
- `backend/app/database.py`
- `backend/alembic/versions/0012_session_tokens.py` (nuevo)
- `backend/tests/conftest.py` (nuevo o ampliado)
- `backend/tests/test_api.py`
- `backend/tests/test_security_tokens.py` (nuevo)
- `backend/tests/test_postgresql_schema.py`
- `backend/README.md`
- `backend/.env.example` (nuevo)

### Frontend

- `frontend/src/api/client.ts`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/pages/ChangePasswordPage.tsx`
- `frontend/src/pages/LoginPage.tsx` (solo si cambia el contrato)
- `frontend/README.md`

### Infraestructura

- `Dockerfile`
- `.github/workflows/ci.yml` (nuevo)
- Opcional `docker-compose.yml` para PostgreSQL local

---

## 14. Comandos útiles

```sh
# Backend
cd backend
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q

# Solo PostgreSQL desechable
TEST_DATABASE_URL='postgresql+psycopg://...' \
  .venv/bin/python -m pytest -q tests/test_postgresql_schema.py

# Generar SQL de migración sin conectar
DATABASE_URL='postgresql+psycopg://...' \
  .venv/bin/alembic upgrade head --sql > sql/esquema_postgresql.sql

# Frontend
cd frontend
npm ci
npm test
npm run lint
npm run build
```

---

## 15. Reglas que no se deben romper

1. No eliminar funcionalidades existentes.
2. No cambiar de framework ni duplicar autenticación.
3. No hacer migraciones destructivas ni `downgrade`.
4. No tocar datos de producción sin respaldo y autorización.
5. No exponer secretos en README, código, logs ni ejemplos.
6. Mantener compatibilidad con clientes que usan `access_token` Bearer.
7. Mantener la autorización en backend; el frontend solo oculta controles.
8. Priorizar cambios pequeños, reversibles y con pruebas.
9. No afirmar que algo está implementado sin evidencia en código y pruebas.
10. Documentar cada cambio en este archivo o en el README correspondiente.

---

## 16. Cómo retomar este trabajo

Si el contexto se pierde:

1. Leer este archivo completo.
2. Revisar `git status` (si hay Git) para saber qué se modificó.
3. Ejecutar la línea base de pruebas.
4. Continuar desde **Pendiente / no hecho**; no rehacer las fases completadas.
5. No aplicar `0012` ni modificar una base real sin respaldo y autorización
   operativa expresa.
6. Al terminar, actualizar la sección 1.1 con comandos y resultados reales.

---

**Última actualización:** 2026-11-25
**Estado:** Fase 0 completada; Fase 1 núcleo implementada y probada (113 passed, 24 skipped backend; 6 passed frontend). Pendientes: validación PostgreSQL real, migración 0012 con autorización operativa y validación de configuración en despliegue.
