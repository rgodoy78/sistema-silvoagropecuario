#!/usr/bin/env bash
# Ejecuta localmente los mismos chequeos que el CI de GitHub
# (.github/workflows/ci.yml). Úsalo antes de hacer merge de un PR.
#   Uso: ./scripts/ci-local.sh
# Requiere el stack de desarrollo (levanta la base de datos si no está arriba).
set -uo pipefail
cd "$(dirname "$0")/.."

PY_IMAGE=python:3.13-slim-trixie
# Mismas versiones de herramientas que el CI, leídas del workflow.
RUFF=$(grep -oP 'ruff==\K[0-9.]+' .github/workflows/ci.yml)
PIP_AUDIT=$(grep -oP 'pip-audit==\K[0-9.]+' .github/workflows/ci.yml)
TRIVY=$(grep -oP 'aquasec/trivy:\K[0-9.]+' .github/workflows/ci.yml)
C="docker compose -f compose.dev.yml"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

results=()
failed=0

step() {
  local name="$1"; shift
  printf '\n\033[1m== %s\033[0m\n' "$name"
  if "$@"; then
    results+=("✅ $name")
  else
    results+=("❌ $name")
    failed=1
  fi
}

run_py() {  # Ejecuta un comando en un contenedor Python limpio con el repo en solo lectura.
  docker run --rm -v "$PWD":/w:ro -w /w "$PY_IMAGE" sh -c "$1"
}

manage() {  # manage.py dentro de la imagen de desarrollo, con el código actual de src/.
  $C run --rm --no-deps -T web python manage.py "$@"
}

$C up -d --wait db >/dev/null 2>&1 || { echo "No se pudo levantar la base de datos"; exit 1; }

step "Lint (ruff $RUFF)" \
  run_py "pip install -q --root-user-action=ignore ruff==$RUFF 2>/dev/null && ruff check --no-cache src"

step "Vulnerabilidades en dependencias (pip-audit $PIP_AUDIT)" \
  run_py "pip install -q --root-user-action=ignore pip-audit==$PIP_AUDIT 2>/dev/null && pip-audit --strict --require-hashes --disable-pip -r requirements.txt"

# También actualiza nexsurcode:dev, la imagen con la que corren los tests de abajo.
step "Build de la imagen" \
  docker build -q -t nexsurcode:ci -t nexsurcode:dev .

step "Django check --deploy" manage check --deploy --fail-level ERROR
step "Migraciones pendientes" manage makemigrations --check --dry-run
step "Tests" manage test --noinput

# Trivy analiza la imagen exportada a un archivo (sin darle acceso al socket de Docker).
step "Escaneo de imagen (Trivy $TRIVY)" sh -c "
  docker save -o '$TMP/image.tar' nexsurcode:ci &&
  docker run --rm -v '$TMP':/in:ro aquasec/trivy:$TRIVY image --quiet --exit-code 1 \
    --severity HIGH,CRITICAL --ignore-unfixed --input /in/image.tar"

printf '\n\033[1m== Resumen\033[0m\n'
printf '%s\n' "${results[@]}"
exit $failed
