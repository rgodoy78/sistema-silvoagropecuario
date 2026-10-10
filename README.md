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

El admin está en la ruta aleatoria definida en `DJANGO_ADMIN_URL` (`.env`).

El código en `src/` se monta en el contenedor y gunicorn recarga solo al guardar.

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
- Rate limiting general y estricto en `/login/`, límites de tamaño y timeouts.
- Dev completo detrás de auth básica (bcrypt).
- Se preserva la IP real del cliente (rootlesskit con port driver `slirp4netns`).

**Django**
- `DEBUG=False`, `ALLOWED_HOSTS` estricto, URL de admin aleatoria.
- HSTS, CSP estricta (`django-csp`), `X-Frame-Options: DENY`, `nosniff`, COOP, Referrer-Policy, Permissions-Policy.
- Cookies `__Host-`, `Secure`, `HttpOnly`, `SameSite=Lax`.
- Contraseñas con Argon2, mínimo 12 caracteres; bloqueo por fuerza bruta con `django-axes` (5 intentos → 1 h).

**GitHub**
- CI: ruff (incluye reglas de seguridad), `pip-audit`, `check --deploy`, tests, build y escaneo Trivy.
- Dependabot para pip, Docker y Actions. Actions fijadas por SHA, `GITHUB_TOKEN` de solo lectura.

## Notas

- La CSP bloquea scripts y estilos inline. Usa archivos estáticos, o `nonce="{{ request.csp_nonce }}"` en las etiquetas `<script>`/`<style>`.
- Si usas `Authorization: Bearer` en una API, quita `proxy_set_header Authorization ""` del sitio en nginx (se puso para no reenviar las credenciales de la auth básica).
