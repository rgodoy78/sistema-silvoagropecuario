# syntax=docker/dockerfile:1

ARG PYTHON_IMAGE=python:3.13-slim-trixie

# --- Etapa 1: instala dependencias en un virtualenv -------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
# --require-hashes: rechaza cualquier paquete cuyo hash no coincida.
RUN /opt/venv/bin/pip install --require-hashes --only-binary=:all: -r /tmp/requirements.txt

# --- Etapa 2: imagen final mínima, sin herramientas de compilación ----------
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
# pip no se necesita en ejecución: se elimina (menos superficie de ataque).
RUN /opt/venv/bin/python -m pip uninstall -y -q pip \
    && rm -rf /usr/local/lib/python3*/site-packages/pip* /usr/local/bin/pip* \
              /usr/local/lib/python3*/ensurepip

WORKDIR /app
# El código pertenece a root: el usuario 'app' solo puede leerlo.
COPY --chmod=644 docker/gunicorn.conf.py /etc/gunicorn.conf.py
COPY --chmod=644 docker/healthcheck.py /usr/local/bin/healthcheck.py
COPY src/ /app/
# Lectura para todos, escritura para nadie excepto root (independiente del umask del host).
RUN chmod -R u=rwX,go=rX /app

# collectstatic no necesita secretos reales ni base de datos.
RUN DJANGO_SECRET_KEY=build-only DB_PASSWORD=build-only \
    python manage.py collectstatic --noinput --verbosity 0

USER app:app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "/usr/local/bin/healthcheck.py"]

CMD ["gunicorn", "--config", "/etc/gunicorn.conf.py", "config.wsgi:application"]
