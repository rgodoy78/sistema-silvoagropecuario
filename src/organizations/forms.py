from django import forms
from django.contrib.auth import get_user_model

from accounts.validators import normalize_rut
from organizations.models import Membership, Organization

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
