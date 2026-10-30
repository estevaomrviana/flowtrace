from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from .utils import get_membership


class OrganizationMemberMixin(AccessMixin):
    """Exige usuário logado e vinculado a uma organização ativa.

    Disponibiliza self.membership e self.organization para a view, e todo
    queryset deve ser filtrado por self.organization.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        self.membership = get_membership(request)
        if self.membership is None:
            return render(request, 'organizations/no_organization.html', status=403)

        self.organization = self.membership.organization

        if not self.has_organization_permission():
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)

    def has_organization_permission(self):
        return True


class OrganizationAdminMixin(OrganizationMemberMixin):
    """Apenas administradores da organização."""

    def has_organization_permission(self):
        return self.membership.is_admin


class ServerManagerMixin(OrganizationMemberMixin):
    """Administradores de organizações autorizadas a cadastrar servidores."""

    def has_organization_permission(self):
        return self.membership.can_manage_servers
