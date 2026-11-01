from django.contrib import admin

from .forms import SubscriberSourceForm
from .models import SubscriberSource


class SubscriberSourceAdminForm(SubscriberSourceForm):
    class Meta(SubscriberSourceForm.Meta):
        fields = ('organization', 'managed_by_platform', *SubscriberSourceForm.Meta.fields)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['managed_by_platform'].initial = True


@admin.register(SubscriberSource)
class SubscriberSourceAdmin(admin.ModelAdmin):
    form = SubscriberSourceAdminForm
    list_display = ('name', 'organization', 'engine', 'connection', 'db_host', 'is_active', 'managed_by_platform')
    list_filter = ('organization', 'engine', 'connection', 'is_active')
    search_fields = ('name', 'db_host', 'organization__name')
    list_select_related = ('organization',)
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('organization', 'name', 'is_active', 'managed_by_platform')}),
        ('Acesso ao banco', {
            'fields': ('engine', 'connection', 'ssh_server', 'db_host', 'db_port', 'db_name', 'db_user', 'db_password'),
            'description': 'A senha é criptografada e nunca exibida. Deixe em branco para manter a salva.',
        }),
        ('Consulta', {'fields': ('table', 'timezone', 'customer_query')}),
        ('Registro', {'fields': ('created_by', 'created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
