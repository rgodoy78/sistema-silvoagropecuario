from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
def home(request):
    return HttpResponse("nexsurcode", content_type="text/plain; charset=utf-8")


@never_cache
@require_GET
def healthz(request):
    """Healthcheck del contenedor: verifica que la base de datos responde."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
