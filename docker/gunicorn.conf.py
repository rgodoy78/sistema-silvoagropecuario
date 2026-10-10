"""Configuración de Gunicorn. Valores ajustables por variables de entorno."""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 30
keepalive = 5

# Recicla workers periódicamente (mitiga fugas de memoria).
max_requests = 1000
max_requests_jitter = 100

# Sistema de archivos de solo lectura: archivos temporales en memoria.
worker_tmp_dir = "/dev/shm"
# Socket de control no usado: menos superficie de ataque.
control_socket_disable = True

# Límites de cabeceras (defensa contra peticiones malformadas).
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Solo nginx puede alcanzar este puerto (red interna de Docker).
forwarded_allow_ips = "*"

# Recarga automática al editar código (solo desarrollo).
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
access_log_format = '%({x-real-ip}i)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'
