from django.urls import include, path

from core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path("cuentas/", include("accounts.urls")),
    path("gestion/", include("accounts.urls_management")),
]
