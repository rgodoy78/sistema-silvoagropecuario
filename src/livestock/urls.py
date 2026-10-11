from django.urls import path

from livestock import views, views_costs, views_health, views_reproduction

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
    path("reproduccion/", views_reproduction.reproduction, name="reproduction"),
    path("reproduccion/servicio/", views_reproduction.service_add, name="service_add"),
    path("animales/<int:pk>/diagnostico/", views_reproduction.check_add, name="check_add"),
    path("animales/<int:pk>/parto/", views_reproduction.calving_add, name="calving_add"),
    path("animales/<int:pk>/destete/", views_reproduction.weaning_add, name="weaning_add"),
    path("reproduccion/<str:kind>/<int:pk>/eliminar/", views_reproduction.event_delete, name="event_delete"),
    path("sanidad/", views_health.health, name="health"),
    path("sanidad/productos/", views_health.product_add, name="product_add"),
    path("sanidad/productos/<int:pk>/", views_health.product_edit, name="product_edit"),
    path("sanidad/tratamiento/", views_health.treatment_add, name="treatment_add"),
    path("sanidad/tratamientos/<int:pk>/eliminar/", views_health.treatment_delete, name="treatment_delete"),
    path("costos/", views_costs.economics, name="economics"),
    path("costos/nuevo/", views_costs.cost_add, name="cost_add"),
    path("costos/<int:pk>/eliminar/", views_costs.cost_delete, name="cost_delete"),
    path("costos/alimentos/", views_costs.feed_item_add, name="feed_item_add"),
    path("costos/alimentos/<int:pk>/", views_costs.feed_item_edit, name="feed_item_edit"),
    path("costos/precios/", views_costs.price_add, name="price_add"),
]
