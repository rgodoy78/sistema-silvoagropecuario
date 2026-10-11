from django.urls import path

from organizations import views_management as views

app_name = "org_management"

urlpatterns = [
    path("", views.organization_list, name="list"),
    path("nueva/", views.organization_create, name="create"),
    path("<int:pk>/", views.organization_detail, name="detail"),
    path("<int:pk>/miembros/", views.member_add, name="member_add"),
    path("miembros/<int:pk>/", views.member_update, name="member_update"),
]
