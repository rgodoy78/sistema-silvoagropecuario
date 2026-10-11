"""Catálogo inicial de razas bovinas presentes en Chile.

La carne nacional proviene sobre todo de razas de doble propósito (Overo
Colorado y Overo Negro); entre las de carne destacan Angus, Hereford y el
Clavel, la única raza chilena.
"""

from django.db import migrations

BREEDS = [
    ("Overo Colorado", "dual"),
    ("Aberdeen Angus", "beef"),
    ("Hereford", "beef"),
    ("Overo Negro", "dual"),
    ("Red Angus", "beef"),
    ("Clavel", "beef"),
    ("Holstein Friesian", "dairy"),
    ("Jersey", "dairy"),
    ("Simmental / Fleckvieh", "dual"),
    ("Normando", "dual"),
    ("Montbéliarde", "dual"),
    ("Charolais", "beef"),
    ("Limousin", "beef"),
    ("Shorthorn", "beef"),
    ("Wagyu", "beef"),
    ("Brangus", "beef"),
    ("Criollo", "other"),
    ("Cruza", "other"),
    ("Otra", "other"),
]


def load(apps, schema_editor):
    Breed = apps.get_model("livestock", "Breed")
    for order, (name, purpose) in enumerate(BREEDS, start=1):
        Breed.objects.update_or_create(name=name, defaults={"purpose": purpose, "order": order * 10})


def unload(apps, schema_editor):
    apps.get_model("livestock", "Breed").objects.filter(name__in=[name for name, _ in BREEDS]).delete()


class Migration(migrations.Migration):
    dependencies = [("livestock", "0001_initial")]

    operations = [migrations.RunPython(load, unload)]
