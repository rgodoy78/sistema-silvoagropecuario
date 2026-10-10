from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.apps import ADMIN_ROLE
from accounts.tests import PASSWORD, current_code, enable_2fa, make_user
from core import charts

SECURE = {"secure": True, "headers": {"host": "testserver"}}


@override_settings(ALLOWED_HOSTS=["testserver"])
class SecurityHeadersTests(TestCase):
    def test_http_redirects_to_https(self):
        response = self.client.get("/cuentas/ingresar/")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response["Location"].startswith("https://"))

    def test_security_headers_present(self):
        response = self.client.get("/cuentas/ingresar/", **SECURE)
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=", response["Strict-Transport-Security"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_home_requires_login(self):
        response = self.client.get("/panel/", **SECURE)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/cuentas/ingresar/", response["Location"])

    def test_landing_is_public(self):
        response = self.client.get("/", **SECURE)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solicitar acceso")
        self.assertContains(response, "datos ilustrativos")
        # Sin estilos ni scripts inline: la CSP los bloquearía.
        self.assertNotContains(response, "style=")
        self.assertNotContains(response, "<script")

    def test_credits_page_lists_every_photo(self):
        from django.contrib.staticfiles import finders

        from core.views import PHOTO_CREDITS

        response = self.client.get("/creditos/", **SECURE)
        self.assertEqual(response.status_code, 200)
        for photo in PHOTO_CREDITS:
            self.assertContains(response, photo["author"])
            self.assertIsNotNone(finders.find(f"img/fotos/{photo['file']}"), photo["file"])

    def test_healthz_reports_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_django_admin_disabled(self):
        from django.apps import apps

        self.assertFalse(apps.is_installed("django.contrib.admin"))
        self.assertEqual(self.client.get("/admin/", **SECURE).status_code, 404)


@override_settings(ALLOWED_HOSTS=["testserver"], SECURE_SSL_REDIRECT=False, AXES_ENABLED=False)
class DashboardTests(TestCase):
    def test_user_sees_sample_data_without_account_stats(self):
        self.client.force_login(make_user())
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Datos de ejemplo")
        self.assertNotContains(response, "Cuentas de usuario")
        self.assertNotContains(response, "style=")
        # Las coordenadas SVG no deben localizarse (es-cl usa coma decimal).
        self.assertNotRegex(response.content.decode(), r'(x|y|width|height|y1|y2)="-?\d+,\d')

    def test_admin_sees_real_account_stats(self):
        admin = make_user(email="admin@example.com")
        admin.groups.add(Group.objects.get(name=ADMIN_ROLE))
        device = enable_2fa(admin)
        make_user(email="pendiente@example.com", status=admin.Status.APPROVAL_PENDING)
        self.client.post(reverse("accounts:login"), {"username": admin.email, "password": PASSWORD})
        self.client.post(reverse("accounts:login_otp"), {"token": current_code(device)})
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Cuentas de usuario")
        users = response.context["users"]
        self.assertEqual((users["active"], users["pending"], users["with_2fa"]), (1, 1, 1))
        self.assertEqual(len(users["signups"]["bars"]), 6)
        self.assertEqual(users["signups"]["bars"][-1]["value"], "2")


class ChartTests(SimpleTestCase):
    def test_number_format_is_chilean(self):
        self.assertEqual(charts.fmt(1234567), "1.234.567")
        self.assertEqual(charts.fmt(2.5), "2,5")

    def test_bar_heights_are_proportional(self):
        chart = charts.bar_chart(["a", "b"], [50, 100])
        a, b = chart["bars"]
        self.assertAlmostEqual(a["h"] * 2, b["h"], delta=0.2)
        self.assertEqual(chart["grid"][-1]["label"], "100")

    def test_integer_axis_has_whole_steps(self):
        labels = [g["label"] for g in charts.bar_chart(["a"], [1], integer=True)["grid"]]
        self.assertEqual(labels, ["0", "1", "2", "3", "4"])
        labels = [g["label"] for g in charts.bar_chart(["a"], [9], integer=True)["grid"]]
        self.assertTrue(all("," not in label for label in labels))

    def test_empty_values_do_not_crash(self):
        self.assertEqual(charts.bar_chart(["a"], [0])["bars"][0]["h"], 0)
        self.assertEqual(charts.donut_chart([])["segments"], [])

    def test_donut_segments_add_up(self):
        chart = charts.donut_chart([("x", 1), ("y", 3)])
        self.assertEqual([s["pct"] for s in chart["segments"]], [25, 75])
        self.assertEqual(chart["total"], "4")
