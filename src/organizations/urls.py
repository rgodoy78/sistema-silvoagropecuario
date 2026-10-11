from django.urls import path

from organizations import views

app_name = "organizations"

urlpatterns = [
    path("cambiar/", views.switch, name="switch"),
    path("equipo/", views.team, name="team"),
    path("equipo/<int:pk>/", views.team_member, name="team_member"),
]
