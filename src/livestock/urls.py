from django.urls import path

from livestock import views

app_name = "livestock"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("animales/", views.animal_list, name="animal_list"),
    path("animales/nuevo/", views.animal_create, name="animal_create"),
    path("animales/<int:pk>/", views.animal_detail, name="animal_detail"),
    path("animales/<int:pk>/editar/", views.animal_edit, name="animal_edit"),
    path("animales/<int:pk>/salida/", views.animal_exit, name="animal_exit"),
    path("animales/<int:pk>/pesaje/", views.weighing_add, name="weighing_add"),
    path("pesajes/<int:pk>/eliminar/", views.weighing_delete, name="weighing_delete"),
    path("pesajes/importar/", views.weighing_import, name="weighing_import"),
    path("traslado/", views.transfer, name="transfer"),
    path("predios/", views.farm_list, name="farm_list"),
    path("predios/nuevo/", views.farm_edit, name="farm_create"),
    path("predios/<int:pk>/", views.farm_detail, name="farm_detail"),
    path("predios/<int:pk>/editar/", views.farm_edit, name="farm_edit"),
    path("predios/<int:pk>/potreros/", views.paddock_add, name="paddock_add"),
    path("potreros/<int:pk>/eliminar/", views.paddock_delete, name="paddock_delete"),
    path("lotes/", views.lot_list, name="lot_list"),
    path("lotes/nuevo/", views.lot_edit, name="lot_create"),
    path("lotes/<int:pk>/", views.lot_edit, name="lot_edit"),
]
