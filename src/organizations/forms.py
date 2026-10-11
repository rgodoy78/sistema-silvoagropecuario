from django import forms
from django.contrib.auth import get_user_model

from accounts.validators import normalize_rut
from organizations.models import Membership, Organization, OrganizationScopedModel

User = get_user_model()


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["name", "rut", "is_active"]

    def clean_rut(self):
        rut = normalize_rut(self.cleaned_data.get("rut", ""))
        if rut and "-" not in rut:
            rut = f"{rut[:-1]}-{rut[-1]}"
        if rut and Organization.objects.filter(rut=rut).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una organización con este RUT.")
        return rut


class MemberAddForm(forms.Form):
    email = forms.EmailField(label="Correo del usuario")
    role = forms.ChoiceField(label="Rol", choices=Membership.Role.choices, initial=Membership.Role.OPERATOR)

    def __init__(self, organization, *args, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean_email(self):
        user = User.objects.filter(email__iexact=self.cleaned_data["email"]).first()
        if user is None:
            raise forms.ValidationError("No existe un usuario con ese correo. Debe registrarse primero.")
        if user.memberships.filter(organization=self.organization).exists():
            raise forms.ValidationError("Ese usuario ya pertenece a esta organización.")
        self.user = user
        return user.email


class MemberRoleForm(forms.Form):
    role = forms.ChoiceField(label="Rol", choices=Membership.Role.choices)


class OrganizationScopedForm(forms.ModelForm):
    """ModelForm para datos de un cliente.

    Limita toda lista de selección de datos de cliente (predios, lotes, ...) a la
    organización activa y asigna esa organización al guardar. Así un id de otra
    organización enviado a mano es rechazado como opción inválida.
    """

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            queryset = getattr(field, "queryset", None)
            if queryset is not None and issubclass(queryset.model, OrganizationScopedModel):
                field.queryset = queryset.filter(organization=organization)

    # Campos asignados por código que igual deben validarse en las restricciones de unicidad.
    validate_assigned = ("organization",)

    def _post_clean(self):
        self.instance.organization = self.organization
        super()._post_clean()

    def _get_validation_exclusions(self):
        return super()._get_validation_exclusions() - set(self.validate_assigned)
