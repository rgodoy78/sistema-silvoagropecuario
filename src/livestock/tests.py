from datetime import date, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.tests import BaseTestCase, make_user
from livestock import services
from livestock.models import (
    Animal,
    Breed,
    Farm,
    HealthProduct,
    Lot,
    Movement,
    Paddock,
    PregnancyCheck,
    Treatment,
    Weighing,
)
from organizations.models import Membership, Organization

TODAY = date.today()


def make_animal(org, farm, diio="12345678", **extra):
    defaults = {"sex": "F", "category": "vaca", "origin": "initial", "entry_date": TODAY - timedelta(days=400)}
    return Animal.objects.create(organization=org, farm=farm, diio=diio, **{**defaults, **extra})


class LivestockTestCase(BaseTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Ganadera Sur")
        self.user = make_user(email="campo@example.com")
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.Role.FIELD_BOSS)
        self.farm = Farm.objects.create(organization=self.org, name="Los Robles", rup="08.1.01.0001")
        self.paddock = Paddock.objects.create(organization=self.org, farm=self.farm, name="Potrero 1")

        self.other_org = Organization.objects.create(name="Competencia")
        self.other_farm = Farm.objects.create(organization=self.other_org, name="Ajeno")
        self.other_animal = make_animal(self.other_org, self.other_farm, diio="99999999")
        self.client.force_login(self.user)


class IsolationTests(LivestockTestCase):
    def test_cannot_view_or_edit_other_organization_animal(self):
        for name in ("animal_detail", "animal_edit", "animal_exit"):
            url = reverse(f"livestock:{name}", args=[self.other_animal.pk])
            self.assertEqual(self.client.get(url).status_code, 404, name)
        url = reverse("livestock:weighing_add", args=[self.other_animal.pk])
        response = self.client.post(url, {"date": TODAY, "weight_kg": "300", "method": "manual"})
        self.assertEqual(response.status_code, 404)

    def test_list_shows_only_own_animals(self):
        make_animal(self.org, self.farm, diio="11111111")
        response = self.client.get(reverse("livestock:animal_list"))
        self.assertContains(response, "11111111")
        self.assertNotContains(response, "99999999")

    def test_cannot_assign_foreign_farm(self):
        response = self.client.post(reverse("livestock:animal_create"), {
            "diio": "22222222", "sex": "F", "category": "vaquilla", "origin": "initial",
            "entry_date": TODAY.isoformat(), "farm": self.other_farm.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Animal.objects.filter(diio="22222222").exists())

    def test_transfer_ignores_foreign_animals(self):
        url = reverse("livestock:transfer")
        response = self.client.post(url, {"animal": [self.other_animal.pk], "date": TODAY, "to_farm": self.farm.pk})
        self.assertRedirects(response, reverse("livestock:animal_list"))
        self.other_animal.refresh_from_db()
        self.assertEqual(self.other_animal.farm, self.other_farm)

    def test_same_diio_allowed_in_another_organization(self):
        make_animal(self.org, self.farm, diio="99999999")
        self.assertEqual(Animal.objects.filter(diio="99999999").count(), 2)

    def test_read_only_role_cannot_write(self):
        viewer = make_user(email="externo@example.com")
        Membership.objects.create(user=viewer, organization=self.org, role=Membership.Role.VIEWER)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("livestock:animal_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("livestock:animal_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("livestock:weighing_import")).status_code, 403)

    def test_user_without_organization_blocked(self):
        self.client.force_login(make_user(email="solo@example.com"))
        self.assertEqual(self.client.get(reverse("livestock:dashboard")).status_code, 403)


class AnimalTests(LivestockTestCase):
    def create(self, **data):
        payload = {
            "diio": "30000001", "tag": "", "sex": "M", "category": "ternero",
            "breed": Breed.objects.get(name="Hereford").pk,
            "birth_date": (TODAY - timedelta(days=30)).isoformat(), "origin": "born", "entry_date": TODAY.isoformat(),
            "farm": self.farm.pk, "paddock": self.paddock.pk, "entry_weight": "45",
        }
        payload.update(data)
        return self.client.post(reverse("livestock:animal_create"), payload)

    def test_breed_catalog_loaded(self):
        self.assertTrue(Breed.objects.filter(name="Overo Colorado", purpose="dual").exists())
        self.assertTrue(Breed.objects.filter(name="Clavel", purpose="beef").exists())

    def test_register_birth_creates_movement_and_weighing(self):
        self.create()
        animal = Animal.objects.get(diio="30000001")
        self.assertEqual(animal.organization, self.org)
        self.assertEqual(animal.movements.get().kind, Movement.Kind.BIRTH)
        self.assertEqual(animal.weighings.get().weight_kg, Decimal("45"))

    def test_category_must_match_sex(self):
        response = self.create(category="vaca")
        self.assertContains(response, "no corresponde al sexo")

    def test_identification_required(self):
        self.assertContains(self.create(diio="", tag=""), "Indica el DIIO")

    def test_duplicate_diio_rejected_with_message(self):
        make_animal(self.org, self.farm, diio="30000001")
        response = self.create()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Animal.objects.filter(organization=self.org, diio="30000001").count(), 1)

    def test_paddock_must_belong_to_farm(self):
        other = Farm.objects.create(organization=self.org, name="Otro predio")
        self.assertContains(self.create(farm=other.pk), "no pertenece al predio")

    def test_future_birth_rejected(self):
        self.assertContains(self.create(birth_date=(TODAY + timedelta(days=2)).isoformat()), "no puede ser futura")

    def test_detail_shows_daily_gain(self):
        animal = make_animal(self.org, self.farm, sex="M", category="novillo")
        Weighing.objects.create(organization=self.org, animal=animal, date=TODAY - timedelta(days=100), weight_kg=300)
        Weighing.objects.create(organization=self.org, animal=animal, date=TODAY, weight_kg=380)
        response = self.client.get(reverse("livestock:animal_detail", args=[animal.pk]))
        self.assertContains(response, "0,80")
        self.assertContains(response, "<polyline")


class MovementTests(LivestockTestCase):
    def setUp(self):
        super().setUp()
        self.animal = make_animal(self.org, self.farm, paddock=self.paddock)

    def test_transfer_between_paddocks_records_history(self):
        p2 = Paddock.objects.create(organization=self.org, farm=self.farm, name="Potrero 2")
        lot = Lot.objects.create(organization=self.org, name="Engorda")
        self.client.post(reverse("livestock:transfer"), {
            "animal": [self.animal.pk], "date": TODAY, "to_farm": self.farm.pk, "to_paddock": p2.pk, "lot": lot.pk,
        })
        self.animal.refresh_from_db()
        self.assertEqual((self.animal.paddock, self.animal.lot), (p2, lot))
        move = self.animal.movements.get(kind=Movement.Kind.TRANSFER)
        self.assertEqual((move.from_paddock, move.to_paddock), (self.paddock, p2))

    def test_transfer_to_other_rup_requires_fma(self):
        other = Farm.objects.create(organization=self.org, name="Veranada", rup="11.2.02.0002")
        data = {"animal": [self.animal.pk], "date": TODAY, "to_farm": other.pk}
        self.assertContains(self.client.post(reverse("livestock:transfer"), data), "requiere el N° de FMA")
        self.client.post(reverse("livestock:transfer"), {**data, "fma": "123456"})
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.farm, other)

    def test_transfer_whole_lot(self):
        lot = Lot.objects.create(organization=self.org, name="Vaquillas")
        self.animal.lot = lot
        self.animal.save()
        response = self.client.get(reverse("livestock:transfer"), {"lote": lot.pk})
        self.assertContains(response, "Trasladar 1 animal")

    def test_sale_removes_from_stock(self):
        url = reverse("livestock:animal_exit", args=[self.animal.pk])
        self.client.post(url, {"kind": "sale", "date": TODAY, "counterparty": "Feria Osorno",
                               "counterparty_rut": "76.086.428-5", "fma": "998877", "weight_kg": "520",
                               "price_clp": "850000"})
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.status, Animal.Status.SOLD)
        self.assertEqual(self.animal.movements.get(kind="sale").counterparty_rut, "76086428-5")
        self.assertNotIn(self.animal, self.client.get(reverse("livestock:animal_list")).context["page"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_death_requires_cause(self):
        url = reverse("livestock:animal_exit", args=[self.animal.pk])
        self.assertContains(self.client.post(url, {"kind": "death", "date": TODAY}), "causa de muerte")
        self.client.post(url, {"kind": "death", "date": TODAY, "cause": "Timpanismo"})
        self.animal.refresh_from_db()
        self.assertEqual(self.animal.status, Animal.Status.DEAD)


class ImportTests(LivestockTestCase):
    def upload(self, content, name="pesaje.csv"):
        return self.client.post(reverse("livestock:weighing_import"), {
            "file": SimpleUploadedFile(name, content.encode("latin-1")), "date": TODAY.isoformat(), "method": "scale",
        })

    def test_imports_semicolon_file_with_decimal_comma_and_eid(self):
        a = make_animal(self.org, self.farm, diio="12345678")
        b = make_animal(self.org, self.farm, diio="", tag="Rosita")
        response = self.upload("EID;Peso;Fecha\n152000012345678;412,5;01-10-2026\nRosita;380;\n99999999;300;\n")
        self.assertContains(response, "2 pesajes importados")
        self.assertContains(response, "99999999")  # pertenece a otra organización: no se asocia
        self.assertEqual(a.weighings.get().weight_kg, Decimal("412.5"))
        self.assertEqual(a.weighings.get().date, date(2026, 10, 1))
        self.assertEqual(b.weighings.get().date, TODAY)
        self.assertFalse(self.other_animal.weighings.exists())

    def test_missing_columns_reported(self):
        self.assertContains(self.upload("animal;cosa\n1;2\n"), "No se encontraron las columnas")

    def test_invalid_weight_reported(self):
        make_animal(self.org, self.farm, diio="12345678")
        self.assertContains(self.upload("DIIO,Peso\n12345678,abc\n"), "Línea 2")

    def test_rejects_non_csv(self):
        self.assertContains(self.upload("x", name="datos.xlsx"), "Sube un archivo .csv")


class DashboardTests(LivestockTestCase):
    def test_empty_state_invites_to_create_farm(self):
        Farm.objects.filter(organization=self.org).delete()
        self.assertContains(self.client.get(reverse("livestock:dashboard")), "Empecemos por tu predio")

    def test_dashboard_with_data(self):
        lot = Lot.objects.create(organization=self.org, name="Engorda")
        animal = make_animal(self.org, self.farm, sex="M", category="novillo", lot=lot)
        Weighing.objects.create(organization=self.org, animal=animal, date=TODAY - timedelta(days=50), weight_kg=300)
        Weighing.objects.create(organization=self.org, animal=animal, date=TODAY, weight_kg=350)
        response = self.client.get(reverse("livestock:dashboard"))
        self.assertContains(response, "Novillo")
        self.assertContains(response, "1,00")
        self.assertEqual(services.herd_daily_gain(self.other_org)["animals"], 0)

    def test_duplicate_farm_name_is_a_form_error(self):
        response = self.client.post(reverse("livestock:farm_create"), {"name": "Los Robles"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Farm.objects.filter(organization=self.org, name="Los Robles").count(), 1)

    def test_paddock_with_animals_cannot_be_deleted(self):
        make_animal(self.org, self.farm, paddock=self.paddock)
        self.client.post(reverse("livestock:paddock_delete", args=[self.paddock.pk]))
        self.assertTrue(Paddock.objects.filter(pk=self.paddock.pk).exists())


class SmokeTests(LivestockTestCase):
    def test_every_page_renders(self):
        lot = Lot.objects.create(organization=self.org, name="Engorda")
        mother = make_animal(self.org, self.farm, diio="40000001")
        calf = make_animal(self.org, self.farm, diio="40000002", sex="M", category="ternero", mother=mother, lot=lot,
                           birth_date=TODAY - timedelta(days=60))
        Weighing.objects.create(organization=self.org, animal=calf, date=TODAY, weight_kg=80)
        pages = [
            ("dashboard", []), ("animal_list", []), ("animal_create", []), ("animal_detail", [mother.pk]),
            ("animal_detail", [calf.pk]), ("animal_edit", [calf.pk]), ("animal_exit", [calf.pk]),
            ("weighing_import", []), ("farm_list", []), ("farm_create", []), ("farm_detail", [self.farm.pk]),
            ("farm_edit", [self.farm.pk]), ("lot_list", []), ("lot_create", []), ("lot_edit", [lot.pk]),
        ]
        for name, args in pages:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f"livestock:{name}", args=args)).status_code, 200)
        response = self.client.get(reverse("livestock:transfer"), {"animal": [mother.pk, calf.pk]})
        self.assertContains(response, "Trasladar 2 animales")
        self.assertContains(self.client.get(reverse("livestock:animal_list"), {"estado": "todos"}), "40000002")


class ReproductionTests(LivestockTestCase):
    def setUp(self):
        super().setUp()
        self.cow = make_animal(self.org, self.farm, diio="50000001", category="vaquilla",
                               breed=Breed.objects.get(name="Hereford"))
        self.bull = make_animal(self.org, self.farm, diio="50000099", sex="M", category="toro")

    def test_bulk_service_only_for_breeding_females(self):
        steer = make_animal(self.org, self.farm, diio="50000002", sex="M", category="novillo")
        url = reverse("livestock:service_add")
        self.client.post(url, {"animal": [self.cow.pk, steer.pk], "kind": "natural", "date": TODAY,
                               "bull": self.bull.pk})
        self.assertEqual(self.cow.services.get().bull, self.bull)
        self.assertFalse(steer.services.exists())

    def test_ai_requires_semen(self):
        response = self.client.post(reverse("livestock:service_add"),
                                    {"animal": [self.cow.pk], "kind": "ai", "date": TODAY})
        self.assertContains(response, "pajuela")

    def test_foreign_bull_rejected(self):
        foreign_bull = make_animal(self.other_org, self.other_farm, diio="77777777", sex="M", category="toro")
        self.client.post(reverse("livestock:service_add"),
                         {"animal": [self.cow.pk], "kind": "natural", "date": TODAY, "bull": foreign_bull.pk})
        self.assertFalse(self.cow.services.exists())

    def test_pregnancy_check_estimates_calving_from_service(self):
        services.register_services([self.cow], self.user, kind="ai", on=TODAY - timedelta(days=60), semen="ANG-123")
        self.client.post(reverse("livestock:check_add", args=[self.cow.pk]),
                         {"date": TODAY, "result": "pregnant", "method": "ultrasound"})
        check = self.cow.pregnancy_checks.get()
        self.assertEqual(check.expected_calving, TODAY - timedelta(days=60) + timedelta(days=283))
        summary = services.reproduction_summary(self.org)
        self.assertEqual(summary["pregnancy_rate"], 100)
        self.assertEqual(summary["pregnant_now"], 1)

    def test_pending_diagnosis(self):
        services.register_services([self.cow], self.user, kind="natural", on=TODAY - timedelta(days=50),
                                   bull=self.bull)
        self.assertEqual(services.reproduction_summary(self.org)["pending"], [self.cow])
        # Si pare después del servicio, ya no está pendiente de diagnóstico.
        services.register_calving(self.cow, self.user, on=TODAY - timedelta(days=5), ease="normal", stillborn=True)
        self.assertEqual(services.reproduction_summary(self.org)["pending"], [])

    def test_calving_creates_calf_and_promotes_heifer(self):
        services.register_services([self.cow], self.user, kind="ai", on=TODAY - timedelta(days=283), semen="ANG-123")
        response = self.client.post(reverse("livestock:calving_add", args=[self.cow.pk]), {
            "date": TODAY, "ease": "normal", "calf_sex": "M", "calf_tag": "T-01", "birth_weight": "36",
        })
        calf = Animal.objects.get(tag="T-01")
        self.assertRedirects(response, reverse("livestock:animal_detail", args=[calf.pk]))
        self.assertEqual((calf.mother, calf.category, calf.sire, calf.breed.name), (self.cow, "ternero", "ANG-123",
                                                                                    "Hereford"))
        self.assertEqual(calf.organization, self.org)
        self.assertEqual(calf.weighings.get().weight_kg, 36)
        self.cow.refresh_from_db()
        self.assertEqual(self.cow.category, "vaca")
        # La preñez quedó cerrada por el parto.
        self.assertEqual(services.reproduction_summary(self.org)["calvings"], 1)

    def test_calving_requires_calf_identification_unless_stillborn(self):
        url = reverse("livestock:calving_add", args=[self.cow.pk])
        self.assertContains(self.client.post(url, {"date": TODAY, "ease": "normal", "calf_sex": "F"}),
                            "identificación visual de la cría")
        self.client.post(url, {"date": TODAY, "ease": "dystocia", "stillborn": "on"})
        calving = self.cow.calvings.get()
        self.assertTrue(calving.stillborn)
        self.assertIsNone(calving.calf)

    def test_weaning_updates_category_and_adjusted_weight(self):
        calf = make_animal(self.org, self.farm, diio="50000010", sex="M", category="ternero",
                           birth_date=TODAY - timedelta(days=200))
        self.client.post(reverse("livestock:weaning_add", args=[calf.pk]),
                         {"date": TODAY, "weight": "215", "new_category": "novillo"})
        calf.refresh_from_db()
        self.assertEqual(calf.category, "novillo")
        weaning = calf.weaning
        self.assertAlmostEqual(weaning.adjusted_205, (215 - 35) / 200 * 205 + 35)
        self.assertEqual(self.client.get(reverse("livestock:weaning_add", args=[calf.pk])).status_code, 404)

    def test_males_cannot_calve(self):
        self.assertEqual(self.client.get(reverse("livestock:calving_add", args=[self.bull.pk])).status_code, 404)

    def test_reproduction_page_renders(self):
        services.register_services([self.cow], self.user, kind="natural", on=TODAY - timedelta(days=200),
                                   bull=self.bull)
        PregnancyCheck.objects.create(organization=self.org, female=self.cow, date=TODAY - timedelta(days=100),
                                      result="pregnant", months_pregnant=4)
        response = self.client.get(reverse("livestock:reproduction"))
        self.assertContains(response, "50000001")
        self.assertContains(self.client.get(reverse("livestock:animal_detail", args=[self.cow.pk])), "Preñada")


class HealthTests(LivestockTestCase):
    def setUp(self):
        super().setUp()
        self.product = HealthProduct.objects.create(organization=self.org, name="Ivermectina 1%",
                                                    kind="antiparasitic", withdrawal_days=35)
        self.lot = Lot.objects.create(organization=self.org, name="Engorda")
        self.a1 = make_animal(self.org, self.farm, diio="60000001", sex="M", category="novillo", lot=self.lot)
        self.a2 = make_animal(self.org, self.farm, diio="60000002", sex="M", category="novillo", lot=self.lot)

    def test_lot_treatment_sets_withdrawal(self):
        self.client.post(reverse("livestock:treatment_add"),
                         {"lote": self.lot.pk, "product": self.product.pk, "date": TODAY, "dose": "10 ml"})
        self.assertEqual(Treatment.objects.filter(organization=self.org).count(), 2)
        self.assertEqual(self.a1.treatments.get().withdrawal_until, TODAY + timedelta(days=35))
        self.assertContains(self.client.get(reverse("livestock:health")), "60000002")

    def test_sale_blocked_during_withdrawal(self):
        services.apply_treatment([self.a1], self.user, product=self.product, on=TODAY - timedelta(days=10))
        url = reverse("livestock:animal_exit", args=[self.a1.pk])
        self.assertContains(self.client.post(url, {"kind": "sale", "date": TODAY}), "período de resguardo")
        self.a1.refresh_from_db()
        self.assertTrue(self.a1.is_active)
        # Una muerte sí se puede registrar.
        self.client.post(url, {"kind": "death", "date": TODAY, "cause": "Neumonía"})
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, "dead")

    def test_sale_allowed_after_withdrawal(self):
        services.apply_treatment([self.a2], self.user, product=self.product, on=TODAY - timedelta(days=40))
        self.client.post(reverse("livestock:animal_exit", args=[self.a2.pk]), {"kind": "sale", "date": TODAY})
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, "sold")

    def test_foreign_product_rejected(self):
        foreign = HealthProduct.objects.create(organization=self.other_org, name="X", kind="other")
        self.client.post(reverse("livestock:treatment_add"),
                         {"animal": [self.a1.pk], "product": foreign.pk, "date": TODAY})
        self.assertFalse(self.a1.treatments.exists())

    def test_cannot_delete_foreign_treatment(self):
        foreign_product = HealthProduct.objects.create(organization=self.other_org, name="Y", kind="other")
        t = Treatment.objects.create(organization=self.other_org, animal=self.other_animal, product=foreign_product,
                                     date=TODAY)
        self.assertEqual(self.client.post(reverse("livestock:treatment_delete", args=[t.pk])).status_code, 404)

    def test_duplicate_product_name_is_form_error(self):
        self.client.post(reverse("livestock:product_add"), {"name": "Ivermectina 1%", "kind": "other",
                                                            "withdrawal_days": 0})
        self.assertEqual(HealthProduct.objects.filter(organization=self.org).count(), 1)
