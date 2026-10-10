from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User

from . import charts

MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Datos ilustrativos para la portada y el panel mientras no existan los módulos
# productivos. Las plantillas los rotulan siempre como "datos de ejemplo".
SAMPLE_SEASON = ["Oct", "Nov", "Dic", "Ene", "Feb", "Mar", "Abr"]
# Misma unidad (toneladas) en un solo eje; la madera se mide aparte.
SAMPLE_PRODUCTION = [
    ("Fruta", [120, 340, 910, 1280, 1150, 760, 380]),
    ("Uva vinífera", [0, 0, 40, 210, 690, 980, 420]),
]
SAMPLE_DESTINATIONS = (
    ["China", "EE.UU.", "Unión Europea", "Corea del Sur", "Japón", "Latinoamérica"],
    [4200, 2600, 1900, 900, 750, 620],
)
SAMPLE_LAND_USE = [("Plantación forestal", 820), ("Frutales", 310), ("Viñedos", 145), ("Praderas y cultivos", 225)]
SAMPLE_HARVEST = [("Cerezas", 100), ("Arándanos", 85), ("Raleo forestal", 65), ("Uva vinífera", 40), ("Manzanas", 20)]
# "good" indica si la variación es favorable (un costo que baja es bueno).
SAMPLE_KPIS = [
    {"label": "Superficie gestionada", "value": "1.500", "unit": "ha", "delta": "+4,2 %", "up": True, "good": True,
     "trend": [1380, 1390, 1400, 1410, 1420, 1425, 1440, 1450, 1460, 1470, 1490, 1500]},
    {"label": "Producción temporada", "value": "8.540", "unit": "t", "delta": "+11,8 %", "up": True, "good": True,
     "trend": [6900, 7100, 7000, 7350, 7400, 7600, 7700, 7900, 8000, 8200, 8350, 8540]},
    {"label": "Ventas exportación", "value": "US$ 10,9", "unit": "M", "delta": "+6,5 %", "up": True, "good": True,
     "trend": [9.6, 9.8, 9.7, 10.0, 10.1, 10.0, 10.3, 10.4, 10.5, 10.6, 10.8, 10.9]},
    {"label": "Costo por hectárea", "value": "$ 1,82", "unit": "M", "delta": "−2,1 %", "up": False, "good": True,
     "trend": [1.90, 1.91, 1.89, 1.88, 1.88, 1.87, 1.86, 1.86, 1.85, 1.84, 1.83, 1.82]},
]

CC = "https://creativecommons.org/licenses/{}/deed.es"
# Fotografías de Wikimedia Commons (recortadas y redimensionadas). Las
# licencias CC exigen atribución: se muestran en /creditos/.
PHOTO_CREDITS = [
    {"file": "hero-colchagua.jpg", "title": "Viñedo en el Valle de Colchagua", "author": "Hiroki Ogawa",
     "license": "CC BY 3.0", "license_url": CC.format("by/3.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Winery_Valle_Colchagua_Chile_-_panoramio_(1).jpg"},
    {"file": "rubro-vitivinicola.jpg", "title": "Hileras de viñedo, Valle de Colchagua", "author": "Hiroki Ogawa",
     "license": "CC BY 3.0", "license_url": CC.format("by/3.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Winery_Valle_Colchagua_Chile_-_panoramio_(2).jpg"},
    {"file": "ingreso-vinedo-andes.jpg", "title": "Viñedo en la precordillera andina", "author": "Beatrice Murch",
     "license": "CC BY-SA 2.0", "license_url": CC.format("by-sa/2.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Chilean_vineyard_in_Andes_foothills.jpg"},
    {"file": "rubro-forestal.jpg", "title": "Plantación forestal en el Biobío", "author": "Eneas De Troya",
     "license": "CC BY 2.0", "license_url": CC.format("by/2.0"),
     "source": "https://commons.wikimedia.org/wiki/File:El_bio_bio_(408501923).jpg"},
    {"file": "rubro-fruticola.jpg", "title": "Cerezas, La Candelaria, Chépica (VI Región)", "author": "Malissette",
     "license": "CC BY-SA 3.0", "license_url": CC.format("by-sa/3.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Cerezas_La_Candelaria_Ch%C3%A9pica_VI_Regi%C3%B3n.JPG"},
    {"file": "rubro-ganadero.jpg", "title": "Ganado frente al volcán Osorno", "author": "Trinicorrea1",
     "license": "CC BY-SA 3.0", "license_url": CC.format("by-sa/3.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Volcan_Osorno_Campo.jpg"},
    {"file": "cta-aysen.jpg", "title": "Ganado Hereford cerca de Coyhaique, Aysén", "author": "Rosario Nieto Chadwick",
     "license": "CC BY 3.0", "license_url": CC.format("by/3.0"),
     "source": "https://commons.wikimedia.org/wiki/File:Animales_Jorge_(123837659).jpeg"},
]


def sample_charts():
    return {
        "production": charts.line_chart(SAMPLE_SEASON, SAMPLE_PRODUCTION),
        "destinations": charts.hbar_chart(*SAMPLE_DESTINATIONS),
        "land_use": charts.stacked_bar(SAMPLE_LAND_USE),
        "harvest": [{"label": label, "pct": pct} for label, pct in SAMPLE_HARVEST],
    }


def sample_kpis():
    return [{**k, "spark": charts.sparkline(k["trend"])} for k in SAMPLE_KPIS]


@require_GET
def landing(request):
    """Portada pública del producto."""
    return render(request, "core/landing.html", {"charts": sample_charts()})


@require_GET
def credits(request):
    """Atribución de fotografías y tipografía."""
    return render(request, "core/credits.html", {"photos": PHOTO_CREDITS})


def _user_stats():
    """Indicadores reales de cuentas para administradores."""
    by_status = dict(User.objects.order_by().values_list("status").annotate(n=Count("id")))
    now = timezone.localtime()
    # Primer día de cada uno de los últimos 6 meses, del más antiguo al actual.
    months = []
    year, month = now.year, now.month
    for _ in range(6):
        months.insert(0, (year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    start = timezone.make_aware(datetime(*months[0], 1))
    joined = {
        (row["m"].year, row["m"].month): row["n"]
        for row in User.objects.filter(date_joined__gte=start)
        .order_by()
        .annotate(m=TruncMonth("date_joined"))
        .values("m")
        .annotate(n=Count("id"))
    }
    statuses = [(label, by_status.get(value, 0)) for value, label in User.Status.choices]
    return {
        "active": by_status.get(User.Status.ACTIVE, 0),
        "pending": by_status.get(User.Status.APPROVAL_PENDING, 0),
        "with_2fa": TOTPDevice.objects.filter(confirmed=True).values("user").distinct().count(),
        "signups": charts.column_chart(
            [MONTHS[m - 1] for _, m in months], [joined.get(ym, 0) for ym in months], integer=True
        ),
        "by_status": charts.stacked_bar([(label, n) for label, n in statuses if n]),
    }


@login_required
@require_GET
def home(request):
    """Panel principal."""
    # Temporada agrícola del hemisferio sur: de julio a junio.
    now = timezone.localtime()
    start = now.year if now.month >= 7 else now.year - 1
    context = {"charts": sample_charts(), "kpis": sample_kpis(), "season": f"{start}–{start + 1}"}
    if request.user.has_perm("accounts.manage_users"):
        context["users"] = _user_stats()
    return render(request, "core/home.html", context)


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
