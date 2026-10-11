import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from livestock import geo
from livestock.models import Farm, Paddock
from livestock.tests import LivestockTestCase
from organizations.models import Membership

# Cuadrado de ~1 km x ~1 km cerca de Los Ángeles (Biobío).
LAT, LON = -37.47, -72.35
D_LAT = 1000 / 111_132
D_LON = 1000 / (111_320 * 0.7937)  # cos(-37.47°)
SQUARE = {"type": "Polygon", "coordinates": [[
    [LON, LAT], [LON + D_LON, LAT], [LON + D_LON, LAT + D_LAT], [LON, LAT + D_LAT], [LON, LAT],
]]}


def kml(*placemarks):
    body = "".join(
        f"<Placemark><name>{name}</name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
        + " ".join(f"{lon},{lat},0" for lon, lat in poly["coordinates"][0])
        + "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
        for name, poly in placemarks
    )
    return f'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>'.encode()


class GeoTests(SimpleTestCase):
    def test_area_of_one_square_km_is_100_ha(self):
        self.assertAlmostEqual(geo.area_ha(SQUARE), 100, delta=1)

    def test_clean_polygon_closes_ring_and_validates(self):
        open_ring = {"type": "Polygon", "coordinates": [SQUARE["coordinates"][0][:-1]]}
        ring = geo.clean_polygon(open_ring)["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        for bad in ({"type": "Point", "coordinates": [1, 2]}, {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]},
                    {"type": "Polygon", "coordinates": [[[0, 0], [200, 0], [0, 1], [0, 0]]]}, "x"):
            with self.assertRaises(geo.GeometryError):
                geo.clean_polygon(bad)

    def test_kml_and_kmz(self):
        data = kml(("Potrero Norte", SQUARE))
        name, polygon = geo.polygons_from_kml(data)[0]
        self.assertEqual(name, "Potrero Norte")
        self.assertAlmostEqual(geo.area_ha(polygon), 100, delta=1)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("doc.kml", data)
        self.assertEqual(len(geo.polygons_from_kml(buffer.getvalue())), 1)

    def test_kml_with_entities_rejected(self):
        evil = b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x SYSTEM "file:///etc/passwd">]><kml>&x;</kml>'
        with self.assertRaises(geo.GeometryError):
            geo.polygons_from_kml(evil)

    def test_contains_and_centroid(self):
        lon, lat = geo.centroid(SQUARE)
        self.assertTrue(geo.contains(SQUARE, lon, lat))
        self.assertFalse(geo.contains(SQUARE, LON - 1, LAT))


class MapViewTests(LivestockTestCase):
    def test_draw_farm_boundary_updates_area(self):
        url = reverse("livestock:boundary_edit", args=["predio", self.farm.pk])
        self.assertContains(self.client.get(url), 'data-map="map-data"')
        response = self.client.post(url, {"geojson": json.dumps(SQUARE), "update_area": "on"})
        self.assertRedirects(response, reverse("livestock:farm_detail", args=[self.farm.pk]))
        self.farm.refresh_from_db()
        self.assertEqual(self.farm.boundary["type"], "Polygon")
        self.assertAlmostEqual(float(self.farm.area_ha), 100, delta=1)

    def test_invalid_geometry_rejected(self):
        url = reverse("livestock:boundary_edit", args=["potrero", self.paddock.pk])
        response = self.client.post(url, {"geojson": '{"type":"Polygon","coordinates":[[[0,0],[1,1]]]}'})
        self.assertContains(response, "al menos 3 puntos")
        self.paddock.refresh_from_db()
        self.assertIsNone(self.paddock.boundary)

    def test_kml_loads_into_editor_without_saving(self):
        url = reverse("livestock:boundary_edit", args=["potrero", self.paddock.pk])
        upload = SimpleUploadedFile("potrero.kml", kml(("P1", SQUARE)))
        response = self.client.post(url, {"file": upload}, follow=True)
        self.assertContains(response, "Revísalo y presiona Guardar")
        self.paddock.refresh_from_db()
        self.assertIsNone(self.paddock.boundary)

    def test_paddocks_from_kml_create_and_update(self):
        url = reverse("livestock:paddocks_from_kml", args=[self.farm.pk])
        upload = SimpleUploadedFile("potreros.kml", kml(("Potrero 1", SQUARE), ("Vega", SQUARE)))
        self.client.post(url, {"file": upload})
        self.paddock.refresh_from_db()
        self.assertIsNotNone(self.paddock.boundary)
        vega = Paddock.objects.get(organization=self.org, farm=self.farm, name="Vega")
        self.assertAlmostEqual(float(vega.area_ha), 100, delta=1)
        self.assertContains(self.client.get(reverse("livestock:farm_detail", args=[self.farm.pk])), "Vega")

    def test_foreign_farm_and_read_only(self):
        url = reverse("livestock:boundary_edit", args=["predio", self.other_farm.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        upload = SimpleUploadedFile("p.kml", kml(("X", SQUARE)))
        foreign = reverse("livestock:paddocks_from_kml", args=[self.other_farm.pk])
        self.assertEqual(self.client.post(foreign, {"file": upload}).status_code, 404)
        Membership.objects.filter(user=self.user).update(role=Membership.Role.VIEWER)
        edit = reverse("livestock:boundary_edit", args=["predio", self.farm.pk])
        self.assertEqual(self.client.get(edit).status_code, 403)
        self.assertEqual(self.client.get(reverse("livestock:farm_detail", args=[self.farm.pk])).status_code, 200)

    @override_settings(ESRI_API_KEY="clave-de-prueba")
    def test_satellite_key_and_csp(self):
        response = self.client.get(reverse("livestock:farm_detail", args=[self.farm.pk]))
        self.assertContains(response, 'data-key="clave-de-prueba"')
        self.assertIn("https://ibasemaps-api.arcgis.com", response["Content-Security-Policy"])
        Farm.objects.filter(pk=self.farm.pk).update(boundary=SQUARE)
        self.assertContains(self.client.get(reverse("livestock:farm_detail", args=[self.farm.pk])), "Polygon")
