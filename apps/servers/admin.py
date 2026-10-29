from django.contrib import admin
from django import forms
from .models import Server


class ServerAdminForm(forms.ModelForm):
    password_field = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Criptografada ao salvar. Deixe em branco para manter a senha atual."
    )

    class Meta:
        model = Server
        exclude = ['_password_encrypted']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('password_field'):
            instance.password = self.cleaned_data['password_field']
        
        if commit:
            instance.save()
        return instance


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    form = ServerAdminForm
    list_display = ('name', 'host', 'username','log_path', 'port')
    search_fields = ('name', 'host',)

