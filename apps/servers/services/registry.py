from django.db import transaction

from apps.organizations.exceptions import QuotaExceeded
from apps.organizations.models import Organization


@transaction.atomic
def register_server(*, organization, created_by, form):
    """Cadastra um servidor da organização respeitando o limite do plano."""
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    if not organization.has_server_quota():
        raise QuotaExceeded('Limite de servidores do plano atingido.')

    return form.save(organization=organization, created_by=created_by)
