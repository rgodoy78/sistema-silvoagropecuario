from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group, Permission

from accounts.models import User
from accounts.validators import normalize_rut

PROFILE_FIELDS = ["first_name", "last_name", "rut", "phone", "position"]


class RutCleanMixin:
    def clean_rut(self):
        rut = normalize_rut(self.cleaned_data.get("rut", ""))
        if rut and "-" not in rut:
            rut = f"{rut[:-1]}-{rut[-1]}"
        if rut and User.objects.filter(rut=rut).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Este RUT ya está registrado.")
        return rut


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="Correo electrónico", widget=forms.EmailInput(attrs={"autofocus": True}))

    error_messages = {
        "invalid_login": "Correo o contraseña incorrectos.",
        # Mismo mensaje que credenciales inválidas: no revela el estado de la cuenta.
        "inactive": "Correo o contraseña incorrectos.",
    }


class SignupForm(RutCleanMixin, forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repite la contraseña", strip=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["email", *PROFILE_FIELDS]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["password1"].help_text = password_validation.password_validators_help_text_html()

    def validate_unique(self):
        # La unicidad del correo se maneja en la vista sin revelar si ya existe.
        exclude = self._get_validation_exclusions()
        exclude.add("email")
        try:
            self.instance.validate_unique(exclude=exclude)
        except forms.ValidationError as e:
            self._update_errors(e)

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            self.instance.email = cleaned.get("email", "")
            self.instance.first_name = cleaned.get("first_name", "")
            self.instance.last_name = cleaned.get("last_name", "")
            try:
                password_validation.validate_password(p1, self.instance)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.status = User.Status.EMAIL_PENDING
        if commit:
            user.save()
        return user


class ProfileForm(RutCleanMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = PROFILE_FIELDS


class OTPTokenForm(forms.Form):
    token = forms.CharField(
        label="Código",
        max_length=16,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": True}),
        help_text="Código de 6 dígitos de tu app autenticadora, o un código de recuperación.",
    )

    def clean_token(self):
        return self.cleaned_data["token"].replace(" ", "").strip()


class PasswordConfirmForm(forms.Form):
    password = forms.CharField(label="Contraseña actual", strip=False, widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError("Contraseña incorrecta.")
        return self.cleaned_data["password"]


# --- Gestión (administradores) ---------------------------------------------


class UserAdminForm(RutCleanMixin, forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        label="Roles", queryset=Group.objects.order_by("name"), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = User
        fields = [*PROFILE_FIELDS, "groups"]


INTERNAL_APPS = ["admin", "auth", "contenttypes", "sessions", "axes", "otp_totp", "otp_static"]


def assignable_permissions():
    """Permisos que se pueden asignar a roles: los de las apps propias."""
    return (
        Permission.objects.exclude(content_type__app_label__in=INTERNAL_APPS)
        .select_related("content_type")
        .order_by("content_type__app_label", "codename")
    )


class RoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        label="Permisos", queryset=Permission.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Group
        fields = ["name", "permissions"]
        labels = {"name": "Nombre del rol"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].queryset = assignable_permissions()
        self.fields["permissions"].label_from_instance = lambda p: p.name
