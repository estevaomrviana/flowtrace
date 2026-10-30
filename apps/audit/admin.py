from django.contrib import admin

from .models import SearchLog


@admin.register(SearchLog)
class SearchLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'organization', 'username', 'server_name', 'action',
                    'query_ip', 'query_port', 'query_datetime', 'status', 'result_count')
    list_filter = ('organization', 'action', 'status')
    search_fields = ('query_ip', 'username', 'server_name', 'error_id')
    date_hierarchy = 'created_at'

    # Auditoria é somente leitura.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
