from django.contrib import admin

from .models import Case, CaseItem, CaseReport


class CaseItemInline(admin.TabularInline):
    model = CaseItem
    fields = ('position', 'ip', 'port', 'moment', 'input_timezone', 'server_name', 'status', 'result_count', 'executed_at')
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = False


class CaseReportInline(admin.TabularInline):
    model = CaseReport
    fields = ('created_at', 'username', 'item_count', 'content_sha256', 'file_sha256')
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ('number', 'organization', 'authority', 'kind', 'received_on', 'deadline', 'status')
    list_filter = ('organization', 'status', 'kind', 'authority_type')
    search_fields = ('number', 'authority', 'organization__name')
    date_hierarchy = 'received_on'
    readonly_fields = ('created_by', 'created_at', 'updated_at', 'answered_at')
    inlines = (CaseItemInline, CaseReportInline)

    # O resultado das consultas é dado pessoal cifrado: a plataforma vê só metadados.
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(CaseReport)
class CaseReportAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'case', 'username', 'item_count', 'content_sha256')
    search_fields = ('content_sha256', 'file_sha256', 'case__number')
    readonly_fields = ('case', 'created_at', 'generated_by', 'username', 'item_count', 'content_sha256', 'file_sha256')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
