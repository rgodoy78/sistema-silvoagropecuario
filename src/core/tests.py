from django.test import TestCase, override_settings

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
        response = self.client.get("/", **SECURE)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/cuentas/ingresar/", response["Location"])

    def test_healthz_reports_ok(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_django_admin_disabled(self):
        from django.apps import apps

        self.assertFalse(apps.is_installed("django.contrib.admin"))
        self.assertEqual(self.client.get("/admin/", **SECURE).status_code, 404)
