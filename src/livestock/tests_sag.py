from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from livestock import sag
from livestock.importer import TEMPLATE_HEADER
from livestock.models import Animal, Breed, Farm, Lot, Paddock
from livestock.tests import TODAY, LivestockTestCase, make_animal
from organizations.models import Membership


class SagTests(LivestockTestCase):
    def test_dea_counts_by_rup_and_official_category(self):
        make_animal(self.org, self.farm, diio="80000001", category="vaca")
        make_animal(self.org, self.farm, diio="80000002", sex="M", category="torete")
        make_animal(self.org, self.farm, diio="80000003", sex="M", category="toro")
        rows, totals = sag.stock_by_rup(self.org)
        self.assertEqual(len(rows), 1)
        self.assertEqual(dict(zip(sag.SAG_CATEGORIES, totals, strict=True))["Toro"], 2)
        response = self.client.get(reverse("livestock:sag"), {"formato": "csv"})
        body = response.content.decode("utf-8-sig")
        self.assertIn("Los Robles;08.1.01.0001;1;0;0;0;0;2;0;3", body)
        self.assertNotIn("Ajeno", body)

    def test_diio_pending(self):
        make_animal(self.org, self.farm, diio="", tag="T1", birth_date=TODAY - timedelta(days=400))
        make_animal(self.org, self.farm, diio="", tag="T2", birth_date=TODAY - timedelta(days=320))
        make_animal(self.org, self.farm, diio="", tag="T3", birth_date=TODAY - timedelta(days=60))
        pending = sag.diio_pending(self.org)
        self.assertEqual([a.tag for a in pending["overdue"]], ["T1"])
        self.assertEqual([a.tag for a in pending["soon"]], ["T2"])
        self.assertContains(self.client.get(reverse("livestock:sag")), "T1")

    def test_fma_sheet(self):
        a = make_animal(self.org, self.farm, diio="80000001", category="vaca")
        b = make_animal(self.org, self.farm, diio="80000002", sex="M", category="novillo")
        url = reverse("livestock:fma_sheet")
        params = {"animal": [a.pk, b.pk], "date": TODAY.isoformat(), "to_rup": "09.1.01.0002",
                  "to_name": "Feria Temuco"}
        response = self.client.get(url, params)
        self.assertContains(response, "Feria Temuco")
        self.assertContains(response, "80000002")
        self.assertContains(response, "data-print")

    def test_fma_requires_single_origin(self):
        other = Farm.objects.create(organization=self.org, name="Veranada")
        a = make_animal(self.org, self.farm, diio="80000001")
        b = make_animal(self.org, other, diio="80000002")
        response = self.client.get(reverse("livestock:fma_sheet"), {"animal": [a.pk, b.pk]})
        self.assertRedirects(response, reverse("livestock:animal_list"))

    def test_fma_ignores_foreign_animals(self):
        response = self.client.get(reverse("livestock:fma_sheet"), {"animal": [self.other_animal.pk]})
        self.assertRedirects(response, reverse("livestock:animal_list"))


class ImportTests(LivestockTestCase):
    def upload(self, name, content):
        return self.client.post(reverse("livestock:animal_import"), {"file": SimpleUploadedFile(name, content)})

    def xlsx(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.append(TEMPLATE_HEADER)
        for row in rows:
            ws.append(row)
        buffer = BytesIO()
        wb.save(buffer)
        return buffer.getvalue()

    def test_template_download(self):
        response = self.client.get(reverse("livestock:animal_import"), {"plantilla": 1})
        self.assertIn("Fecha nacimiento", response.content.decode("utf-8-sig"))

    def test_import_xlsx_with_mother_in_file(self):
        content = self.xlsx([
            ["90000001", "", "Hembra", "Vaca", "Hereford", TODAY - timedelta(days=2000), "los robles", "Potrero 1",
             "Cría", 480, TODAY, "", ""],
            ["", "T-9", "Macho", "Ternero", "", "10-08-2026", "Los Robles", "Potrero Nuevo", "", "", "",
             "90000001", "ANG-1"],
        ])
        response = self.upload("rebano.xlsx", content)
        self.assertContains(response, "2 animales importados")
        cow, calf = Animal.objects.get(diio="90000001"), Animal.objects.get(tag="T-9")
        hereford = Breed.objects.get(name="Hereford")
        self.assertEqual((cow.breed, cow.paddock, cow.lot.name), (hereford, self.paddock, "Cría"))
        self.assertEqual(cow.weighings.get().weight_kg, 480)
        self.assertEqual((calf.mother, calf.sire), (cow, "ANG-1"))
        self.assertTrue(Paddock.objects.filter(organization=self.org, name="Potrero Nuevo").exists())
        self.assertEqual(cow.movements.get().kind, "initial")

    def test_errors_import_nothing(self):
        csv = (
            "DIIO;Identificación;Sexo;Categoría;Predio\n"
            "91000001;;Hembra;Vaca;Los Robles\n"
            "91000002;;Macho;Vaca;Los Robles\n"
            "91000001;;Hembra;Vaquilla;Los Robles\n"
            ";;Hembra;Vaca;Inexistente\n"
        )
        response = self.upload("rebano.csv", csv.encode("utf-8"))
        self.assertContains(response, "No se importó ningún animal")
        self.assertContains(response, "Fila 3")
        self.assertContains(response, "repetido")
        self.assertContains(response, "no existe")
        self.assertFalse(Animal.objects.filter(diio__startswith="91").exists())
        self.assertFalse(Lot.objects.filter(organization=self.org).exists())

    def test_diio_of_other_organization_is_not_a_conflict(self):
        response = self.upload("r.csv", "DIIO;Sexo;Categoría;Predio\n99999999;Hembra;Vaca;Los Robles\n".encode())
        self.assertContains(response, "1 animales importados")

    def test_missing_columns_and_corrupt_file(self):
        self.assertContains(self.upload("r.csv", b"foo;bar\n1;2\n"), "Faltan columnas")
        self.assertContains(self.upload("r.xlsx", b"no es un excel"), "No se pudo leer el archivo")

    def test_read_only_role_cannot_import(self):
        Membership.objects.filter(user=self.user).update(role=Membership.Role.ACCOUNTANT)
        self.assertEqual(self.client.get(reverse("livestock:animal_import")).status_code, 403)
