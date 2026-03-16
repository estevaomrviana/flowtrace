from django.contrib import admin
from django import forms
from .models import Server


class ServerAdminForm(forms.ModelForm):
    password_field = forms.CharField(
        label="Senha",
        widget=forms.PasswordInput(render_value=True),
        required=False,
        help_text="A senha será criptografada automaticamente ao salvar."
    )

    class Meta:
        model = Server
        exclude = ['_password_encrypted']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['password_field'].initial = self.instance.password

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

