from django.conf import settings
from django.contrib import admin
from django.urls import path

from core import views

admin.site.site_header = "nexsurcode"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.healthz, name="healthz"),
    path(settings.ADMIN_URL, admin.site.urls),
]
