#!/usr/bin/env bash
# Crea .env y los archivos de secretos si no existen. Nunca sobrescribe.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077

rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Creado .env"
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
# Contraseña de aplicación de Gmail: se completa a mano (vacío = sin SMTP).
[[ -f secrets/email_password ]] || { : > secrets/email_password; echo "Creado secrets/email_password (vacío)"; }
# API key de ArcGIS para el fondo satelital de los mapas: se completa a mano (vacío = sin fondo).
[[ -f secrets/esri_api_key ]] || { : > secrets/esri_api_key; echo "Creado secrets/esri_api_key (vacío)"; }

# El directorio es 700 (solo tu usuario). Los archivos deben ser legibles
# por el usuario no-root dentro del contenedor (Docker rootless no permite
# ajustar el dueño de los secretos).
chmod 644 secrets/*
