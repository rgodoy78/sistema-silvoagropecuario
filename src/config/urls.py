from django.urls import include, path

from core import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("panel/", views.home, name="home"),
    path("creditos/", views.credits, name="credits"),
    path("healthz/", views.healthz, name="healthz"),
    path("cuentas/", include("accounts.urls")),
    path("gestion/organizaciones/", include("organizations.urls_management")),
    path("gestion/", include("accounts.urls_management")),
    path("organizacion/", include("organizations.urls")),
]
