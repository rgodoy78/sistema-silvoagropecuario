from django.urls import path

from accounts import views_management as views

app_name = "management"

urlpatterns = [
    path("usuarios/", views.user_list, name="user_list"),
    path("usuarios/<int:pk>/", views.user_edit, name="user_edit"),
    path("usuarios/<int:pk>/accion/", views.user_action, name="user_action"),
    path("roles/", views.role_list, name="role_list"),
    path("roles/nuevo/", views.role_edit, name="role_create"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
    path("roles/<int:pk>/eliminar/", views.role_delete, name="role_delete"),
]
