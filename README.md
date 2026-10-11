# nexsurcode

Django 5.2 LTS + PostgreSQL 18 en Docker (rootless), detrás del proxy nginx compartido de `../proxy`.

## Arquitectura

```
Internet ──► nginx (../proxy) ──red "edge"──► web (gunicorn/Django) ──red "backend" (interna)──► db (PostgreSQL)
             TLS, auth básica (dev),                                   sin salida a internet
             rate limiting
```

| Ambiente | Directorio en el servidor | Rama | Dominio |
|---|---|---|---|
| Desarrollo | `~/docker/nexsurcode-dev` | `develop` | dev.nexsurcode.com |
| Producción | `~/docker/nexsurcode-prod` (pendiente) | `main` | nexsurcode.com |

## Puesta en marcha (desarrollo)

```bash
./scripts/init-env.sh                          # crea .env y secrets/ (no sobrescribe)
docker compose -f compose.dev.yml up -d --build
docker compose -f compose.dev.yml exec web python manage.py createsuperuser
```

Ese primer superusuario deberá configurar 2FA en su primer ingreso.

## Cuentas de usuario

No se usa el admin de Django: la gestión de usuarios, roles y perfiles es propia
(app `accounts`).

- **Login con correo** (`/cuentas/ingresar/`) + 2FA (TOTP) si el usuario lo activó.
- **Registro** (`/cuentas/registro/`): confirmar correo → pendiente de aprobación →
  un administrador aprueba o rechaza en `/gestion/usuarios/` → se notifica por correo.
- **Roles** = grupos de Django con permisos (`/gestion/roles/`). El rol
  `Administrador` (permiso `accounts.manage_users`) gestiona usuarios y roles.
- **2FA obligatorio para administradores**: sin 2FA verificado solo pueden ir a
  configurarlo. Para el resto es opcional. Incluye 10 códigos de recuperación.
- Si alguien pierde su teléfono, un administrador puede "Reiniciar 2FA".
- **Recuperar contraseña** por correo (`/cuentas/recuperar/`, enlace válido 1 hora).

### Correo con Gmail

1. En la cuenta de Google: activa la verificación en 2 pasos y crea una
   **contraseña de aplicación** (myaccount.google.com/apppasswords).
2. Guárdala: `printf '%s' 'xxxx xxxx xxxx xxxx' > secrets/email_password`
3. En `.env`:
   ```
   DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   DJANGO_EMAIL_USER=tu-cuenta@gmail.com
   DJANGO_DEFAULT_FROM_EMAIL=ERP Silvoagropecuario <tu-cuenta@gmail.com>
   ```
4. `docker compose -f compose.dev.yml up -d`

Mientras no esté configurado, los correos aparecen en `docker compose -f compose.dev.yml logs web`.

El código en `src/` se monta en el contenedor y gunicorn recarga solo al guardar.

### Mapas satelitales (Esri ArcGIS)

Los mapas de predios y potreros usan la imagen satelital *World Imagery* de Esri
(plan gratuito de ArcGIS Location Platform: 2.000.000 de teselas al mes; uso
comercial permitido). Sin API key los mapas funcionan sobre un fondo neutro.

1. Crea una cuenta en [location.arcgis.com](https://location.arcgis.com) y una
   **API key** con solo el privilegio de *basemaps*.
2. En la configuración de la key, restringe los **referrers** a
   `https://dev.nexsurcode.com` (y luego `https://nexsurcode.com`): la key viaja
   al navegador en la URL de las teselas.
3. Guárdala: `printf '%s' 'AAPK...' > secrets/esri_api_key`
4. `docker compose -f compose.dev.yml up -d`

## Comandos útiles

```bash
alias dc='docker compose -f compose.dev.yml'
dc logs -f web
dc run --rm manage makemigrations              # escribe en src/ (servicio con montaje rw)
dc run --rm manage startapp blog
dc run --rm migrate                             # aplicar migraciones
dc exec web python manage.py test
dc exec -u postgres db psql -d nexsurcode       # consola SQL (superusuario)
./scripts/lock-deps.sh                          # tras editar requirements.in
./scripts/ci-local.sh                           # mismos chequeos que el CI de GitHub
```

## Seguridad aplicada

**Contenedores**
- Docker rootless: root del contenedor ≠ root del servidor.
- Django corre como usuario sin privilegios (uid 10001), sistema de archivos de solo lectura, `cap_drop: ALL`, `no-new-privileges`, límites de memoria y procesos.
- Imagen multi-etapa sin compiladores ni `pip`; dependencias instaladas con `--require-hashes`.
- PostgreSQL sin puertos publicados, en red interna sin salida a internet; Django usa un rol **sin superusuario**; autenticación SCRAM-SHA-256.
- Secretos en `secrets/` (montados en `/run/secrets`), nunca en variables de entorno ni en git.

**Proxy (nginx)**
- TLS 1.2/1.3 (Let's Encrypt, renovación automática), redirección HTTP→HTTPS.
- Peticiones con `Host` desconocido se descartan (escaneos por IP).
- Rate limiting general y estricto en `/cuentas/` (login, 2FA, registro, recuperación), límites de tamaño y timeouts.
- Dev completo detrás de auth básica (bcrypt).
- Se preserva la IP real del cliente (rootlesskit con port driver `slirp4netns`).

**Django**
- `DEBUG=False`, `ALLOWED_HOSTS` estricto, admin de Django deshabilitado (menos superficie de ataque).
- 2FA obligatorio para administradores; el registro no revela qué correos existen; los enlaces de confirmación requieren POST (los escáneres de enlaces no los activan).
- HSTS, CSP estricta (`django-csp`), `X-Frame-Options: DENY`, `nosniff`, COOP, Referrer-Policy, Permissions-Policy.
- Cookies `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`.
- Contraseñas con Argon2, mínimo 12 caracteres; bloqueo por fuerza bruta con `django-axes` (5 intentos → 1 h).

**GitHub**
- CI: ruff (incluye reglas de seguridad), `pip-audit`, `check --deploy`, tests, build y escaneo Trivy.
- Dependabot para pip, Docker y Actions. Actions fijadas por SHA, `GITHUB_TOKEN` de solo lectura.

## Notas

- `/` es la portada pública y `/panel/` el panel (requiere sesión). Los gráficos son SVG generados en el servidor (`core/charts.py`, plantillas en `templates/core/charts/`), sin JavaScript. Los indicadores de temporada son datos de ejemplo (`SAMPLE_*` en `core/views.py`) hasta que existan los módulos productivos; los de cuentas de usuario son reales.
- Fotografías en `static/img/fotos/`, de Wikimedia Commons con licencias CC que exigen atribución: al agregar o cambiar una, actualiza `PHOTO_CREDITS` en `core/views.py` (se muestra en `/creditos/`).
- Tipografía Montserrat servida localmente desde `static/fonts/` (licencia OFL en `OFL.txt`).
- La CSP bloquea scripts y estilos inline. Usa archivos estáticos, o `nonce="{{ request.csp_nonce }}"` en las etiquetas `<script>`/`<style>`.
- Si usas `Authorization: Bearer` en una API, quita `proxy_set_header Authorization ""` del sitio en nginx (se puso para no reenviar las credenciales de la auth básica).
