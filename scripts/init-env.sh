#!/usr/bin/env bash
# Crea .env y los archivos de secretos si no existen. Nunca sobrescribe.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

if [[ ! -f .env ]]; then
  admin_path="admin-$(python3 -c 'import secrets; print(secrets.token_hex(8))')/"
  sed "s|^DJANGO_ADMIN_URL=.*|DJANGO_ADMIN_URL=${admin_path}|" .env.example > .env
  echo "Creado .env (admin en /${admin_path})"
fi

mkdir -p secrets
chmod 700 secrets
for name in django_secret_key:64 postgres_password:32 db_app_password:32; do
  file="secrets/${name%%:*}"
  if [[ ! -f "$file" ]]; then
    rand "${name##*:}" > "$file"
    echo "Creado $file"
  fi
done
# El directorio es 700 (solo tu usuario). Los archivos deben ser legibles
# por el usuario no-root dentro del contenedor (Docker rootless no permite
# ajustar el dueño de los secretos).
chmod 644 secrets/*
