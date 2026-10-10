from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import User


class UserModelTests(TestCase):
    def test_custom_user_model_is_active(self):
        self.assertIs(get_user_model(), User)

    def test_password_is_hashed_with_argon2(self):
        user = User.objects.create_user(username="ana", password="una-clave-larga-segura")
        self.assertTrue(user.password.startswith("argon2"))
