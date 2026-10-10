from django.urls import include, path

from core import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("panel/", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("cuentas/", include("accounts.urls")),
    path("gestion/", include("accounts.urls_management")),
]
