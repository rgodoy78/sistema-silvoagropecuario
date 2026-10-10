#!/bin/sh
# Se ejecuta solo al inicializar un volumen vacío de PostgreSQL.
# Crea el rol de la aplicación (sin superusuario) y le cede la base de datos.
set -eu

app_password="$(cat /run/secrets/db_app_password)"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$DB_USER" -v app_password="$app_password" -v db_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
  NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS CREATEDB;
ALTER DATABASE :"db_name" OWNER TO :"app_user";
REVOKE ALL ON DATABASE :"db_name" FROM PUBLIC;
SQL
