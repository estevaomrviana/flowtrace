from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count, Q

from apps.servers.models import Server

from .models import Membership, Organization

User = get_user_model()


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ('user',)
    fields = ('user', 'role', 'created_at')
    readonly_fields = ('created_at',)


class ServerInline(admin.TabularInline):
    model = Server
    extra = 0
    fields = ('name', 'host', 'is_active', 'managed_by_platform')
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'servers_usage', 'members_usage', 'can_manage_servers', 'created_at')
    list_filter = ('is_active', 'can_manage_servers')
    search_fields = ('name', 'slug', 'document')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (MembershipInline, ServerInline)
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'document', 'is_active')}),
        ('Plano e permissões', {'fields': ('max_servers', 'max_members', 'can_manage_servers')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _servers=Count('servers', distinct=True),
            _members=Count('memberships', filter=Q(memberships__user__is_active=True), distinct=True),
        )

    @admin.display(description='servidores', ordering='_servers')
    def servers_usage(self, obj):
        return f'{obj._servers} / {obj.max_servers if obj.max_servers is not None else "∞"}'

    @admin.display(description='usuários', ordering='_members')
    def members_usage(self, obj):
        return f'{obj._members} / {obj.max_members if obj.max_members is not None else "∞"}'


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'created_at')
    list_filter = ('organization', 'role')
    search_fields = ('user__username', 'user__email', 'organization__name')
    autocomplete_fields = ('user', 'organization')
    list_select_related = ('user', 'organization')


class UserMembershipInline(admin.StackedInline):
    model = Membership
    can_delete = False
    autocomplete_fields = ('organization',)
    fields = ('organization', 'role')


admin.site.unregister(User)


@admin.register(User)
class PlatformUserAdmin(UserAdmin):
    inlines = (UserMembershipInline,)
    list_display = ('username', 'email', 'first_name', 'organization', 'is_active', 'is_staff')
    list_select_related = ('membership__organization',)
    list_filter = ('is_active', 'is_staff', 'membership__organization')

    @admin.display(description='organização', ordering='membership__organization__name')
    def organization(self, obj):
        membership = getattr(obj, 'membership', None)
        return membership.organization if membership else '—'
