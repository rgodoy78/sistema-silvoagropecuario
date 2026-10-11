from django.contrib.auth.models import Group
from django.urls import reverse

from accounts.apps import ADMIN_ROLE
from accounts.tests import PASSWORD, BaseTestCase, current_code, enable_2fa, make_user
from organizations.middleware import SESSION_KEY
from organizations.models import Membership, Organization

Role = Membership.Role


def login_verified(client, user):
    """Inicia sesión con 2FA (obligatorio para administradores)."""
    device = enable_2fa(user)
    client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})
    client.post(reverse("accounts:login_otp"), {"token": current_code(device)})


class CurrentOrganizationTests(BaseTestCase):
    def setUp(self):
        self.user = make_user()
        self.alfa = Organization.objects.create(name="Agrícola Alfa")
        self.beta = Organization.objects.create(name="Ganadera Beta")
        self.otra = Organization.objects.create(name="Otra")
        Membership.objects.create(user=self.user, organization=self.alfa, role=Role.OPERATOR)
        Membership.objects.create(user=self.user, organization=self.beta, role=Role.OPERATOR)
        self.client.force_login(self.user)

    def current(self):
        return self.client.get(reverse("home")).wsgi_request.organization

    def test_defaults_to_first_organization(self):
        self.assertEqual(self.current(), self.alfa)

    def test_switch_between_own_organizations(self):
        response = self.client.post(reverse("organizations:switch"), {"organizacion": self.beta.pk, "next": "/panel/"})
        self.assertRedirects(response, "/panel/")
        self.assertEqual(self.current(), self.beta)

    def test_cannot_switch_to_foreign_organization(self):
        response = self.client.post(reverse("organizations:switch"), {"organizacion": self.otra.pk})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.current(), self.alfa)

    def test_tampered_session_falls_back_to_own_organization(self):
        session = self.client.session
        session[SESSION_KEY] = self.otra.pk
        session.save()
        self.assertEqual(self.current(), self.alfa)

    def test_switch_rejects_external_redirect(self):
        response = self.client.post(
            reverse("organizations:switch"), {"organizacion": self.beta.pk, "next": "https://malo.example.com/"}
        )
        self.assertRedirects(response, reverse("home"))

    def test_inactive_organization_is_not_accessible(self):
        self.alfa.is_active = False
        self.alfa.save()
        self.assertEqual(self.current(), self.beta)

    def test_switcher_shown_with_several_organizations(self):
        self.assertContains(self.client.get(reverse("home")), "org-switch")


class TeamTests(BaseTestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Ganadera Beta")
        self.admin = make_user(email="jefa@example.com")
        self.worker = make_user(email="operario@example.com")
        Membership.objects.create(user=self.admin, organization=self.org, role=Role.ADMIN)
        self.worker_m = Membership.objects.create(user=self.worker, organization=self.org, role=Role.OPERATOR)

        self.foreign_org = Organization.objects.create(name="Competencia")
        self.foreign_m = Membership.objects.create(
            user=make_user(email="ajeno@example.com"), organization=self.foreign_org, role=Role.ADMIN
        )

    def test_organization_admin_must_use_2fa(self):
        self.assertTrue(self.admin.is_administrator)
        self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": PASSWORD})
        self.assertRedirects(self.client.get(reverse("organizations:team")), reverse("accounts:otp_setup"))

    def test_admin_sees_only_own_members(self):
        login_verified(self.client, self.admin)
        response = self.client.get(reverse("organizations:team"))
        self.assertContains(response, "operario@example.com")
        self.assertNotContains(response, "ajeno@example.com")

    def test_admin_changes_role_and_removes_member(self):
        login_verified(self.client, self.admin)
        url = reverse("organizations:team_member", args=[self.worker_m.pk])
        self.client.post(url, {"accion": "rol", "role": Role.FIELD_BOSS})
        self.worker_m.refresh_from_db()
        self.assertEqual(self.worker_m.role, Role.FIELD_BOSS)
        self.client.post(url, {"accion": "quitar"})
        self.assertFalse(Membership.objects.filter(pk=self.worker_m.pk).exists())

    def test_admin_cannot_touch_other_organization(self):
        login_verified(self.client, self.admin)
        url = reverse("organizations:team_member", args=[self.foreign_m.pk])
        self.assertEqual(self.client.post(url, {"accion": "quitar"}).status_code, 404)
        self.assertTrue(Membership.objects.filter(pk=self.foreign_m.pk).exists())

    def test_admin_cannot_change_own_role(self):
        login_verified(self.client, self.admin)
        own = Membership.objects.get(user=self.admin)
        self.client.post(reverse("organizations:team_member", args=[own.pk]), {"accion": "rol", "role": Role.VIEWER})
        own.refresh_from_db()
        self.assertEqual(own.role, Role.ADMIN)

    def test_invalid_role_rejected(self):
        login_verified(self.client, self.admin)
        url = reverse("organizations:team_member", args=[self.worker_m.pk])
        self.client.post(url, {"accion": "rol", "role": "dueño_supremo"})
        self.worker_m.refresh_from_db()
        self.assertEqual(self.worker_m.role, Role.OPERATOR)

    def test_regular_member_forbidden(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse("organizations:team")).status_code, 403)

    def test_user_without_organization_sees_notice(self):
        self.client.force_login(make_user(email="solo@example.com"))
        response = self.client.get(reverse("organizations:team"))
        self.assertContains(response, "no tienes una organización", status_code=403)
        self.assertContains(self.client.get(reverse("home")), "Aún no perteneces")


class OrganizationManagementTests(BaseTestCase):
    def setUp(self):
        self.sysadmin = make_user(email="admin@example.com")
        self.sysadmin.groups.add(Group.objects.get(name=ADMIN_ROLE))

    def test_regular_user_forbidden(self):
        self.client.force_login(make_user(email="otro@example.com"))
        self.assertEqual(self.client.get(reverse("org_management:list")).status_code, 403)

    def test_organization_admin_is_not_system_admin(self):
        org_admin = make_user(email="jefa@example.com")
        org = Organization.objects.create(name="Beta")
        Membership.objects.create(user=org_admin, organization=org, role=Role.ADMIN)
        login_verified(self.client, org_admin)
        self.assertEqual(self.client.get(reverse("org_management:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("management:user_list")).status_code, 403)

    def test_create_organization_from_signup_request(self):
        applicant = make_user(email="nuevo@example.com", company="Ganadera Los Robles")
        login_verified(self.client, self.sysadmin)
        url = f"{reverse('org_management:create')}?usuario={applicant.pk}"
        self.assertContains(self.client.get(url), "Ganadera Los Robles")
        response = self.client.post(url, {"name": "Ganadera Los Robles", "rut": "76.086.428-5", "is_active": "on"})
        self.assertRedirects(response, reverse("management:user_edit", args=[applicant.pk]))
        org = Organization.objects.get(name="Ganadera Los Robles")
        self.assertEqual(org.rut, "76086428-5")
        self.assertTrue(Membership.objects.filter(user=applicant, organization=org, role=Role.ADMIN).exists())

    def test_add_member_by_email(self):
        org = Organization.objects.create(name="Beta")
        user = make_user(email="vet@example.com")
        login_verified(self.client, self.sysadmin)
        add = reverse("org_management:member_add", args=[org.pk])
        self.client.post(add, {"email": "VET@example.com", "role": Role.VIEWER})
        self.assertTrue(Membership.objects.filter(user=user, organization=org, role=Role.VIEWER).exists())
        # Duplicado y correo inexistente no crean nada.
        self.client.post(add, {"email": "vet@example.com", "role": Role.ADMIN})
        self.client.post(add, {"email": "nadie@example.com", "role": Role.ADMIN})
        self.assertEqual(org.memberships.count(), 1)

    def test_duplicate_rut_rejected(self):
        Organization.objects.create(name="Alfa", rut="76086428-5")
        login_verified(self.client, self.sysadmin)
        response = self.client.post(reverse("org_management:create"), {"name": "Beta", "rut": "76.086.428-5"})
        self.assertContains(response, "Ya existe una organización con este RUT")
