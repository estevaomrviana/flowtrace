from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import UserCreationForm

from apps.core.forms import StyledFormMixin

from .models import Membership

User = get_user_model()


class MemberCreateForm(StyledFormMixin, UserCreationForm):
    role = forms.ChoiceField(label='Perfil', choices=Membership.Role.choices, initial=Membership.Role.OPERATOR)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('first_name', 'last_name', 'email', 'username')
        labels = {'first_name': 'Nome', 'last_name': 'Sobrenome', 'email': 'E-mail', 'username': 'Usuário'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['email'].required = True


class MemberUpdateForm(StyledFormMixin, forms.ModelForm):
    role = forms.ChoiceField(label='Perfil', choices=Membership.Role.choices)
    new_password = forms.CharField(
        label='Nova senha', required=False, strip=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='Preencha apenas para redefinir a senha do usuário.',
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'is_active')
        labels = {'first_name': 'Nome', 'last_name': 'Sobrenome', 'email': 'E-mail', 'is_active': 'Acesso ativo'}

    def __init__(self, *args, membership, editing_self=False, **kwargs):
        super().__init__(*args, instance=membership.user, **kwargs)
        self.membership = membership
        self.fields['role'].initial = membership.role
        self.fields['first_name'].required = True
        self.fields['email'].required = True

        if editing_self:
            # Ninguém remove o próprio acesso de administrador.
            for name in ('role', 'is_active'):
                self.fields[name].disabled = True

    def clean_new_password(self):
        password = self.cleaned_data.get('new_password')
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('new_password'):
            user.set_password(self.cleaned_data['new_password'])
        self.membership.role = self.cleaned_data['role']
        if commit:
            user.save()
            self.membership.save(update_fields=['role', 'updated_at'])
        return self.membership

