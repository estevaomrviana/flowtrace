from django.contrib import admin
from django.utils.html import format_html

from .forms import ServerForm
from .models import Server


class ServerAdminForm(ServerForm):
    class Meta(ServerForm.Meta):
        fields = ('organization', 'managed_by_platform', *ServerForm.Meta.fields)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            # Cadastrado pela plataforma: por padrão a organização só usa.
            self.fields['managed_by_platform'].initial = True


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    form = ServerAdminForm
    list_display = ('name', 'organization', 'host', 'port', 'is_active', 'managed_by_platform', 'host_key_status')
    list_filter = ('organization', 'is_active', 'managed_by_platform')
    search_fields = ('name', 'host', 'organization__name')
    list_select_related = ('organization', 'credential')
    readonly_fields = ('host_key_status', 'created_by', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('organization', 'name', 'host', 'port', 'log_path', 'is_active', 'managed_by_platform')}),
        ('Acesso SSH', {
            'fields': ('username', 'auth_method', 'password', 'private_key', 'key_passphrase', 'host_key_status'),
            'description': 'Os segredos são criptografados e nunca exibidos. Deixe em branco para manter os valores salvos.',
        }),
        ('Registro', {'fields': ('created_by', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='chave do host')
    def host_key_status(self, obj):
        credential = getattr(obj, 'credential', None) if obj and obj.pk else None
        if credential is None or not credential.host_key:
            return 'Ainda não verificada'
        return format_html(
            '{}<br><small>verificada em {:%d/%m/%Y %H:%M}</small>',
            credential.host_key.split()[0], credential.host_key_verified_at,
        )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        form.save_credential()
