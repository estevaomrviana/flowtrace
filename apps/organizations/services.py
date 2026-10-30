from django.db import transaction

from .exceptions import QuotaExceeded
from .models import Membership, Organization


def _locked(organization):
    """Recarrega a organização com lock, evitando estourar a cota em requisições simultâneas."""
    return Organization.objects.select_for_update().get(pk=organization.pk)


@transaction.atomic
def add_member(*, organization, form):
    organization = _locked(organization)
    if not organization.has_member_quota():
        raise QuotaExceeded('Limite de usuários do plano atingido.')

    user = form.save()
    return Membership.objects.create(
        user=user, organization=organization, role=form.cleaned_data['role'],
    )


@transaction.atomic
def update_member(*, form):
    membership = form.membership
    reactivating = 'is_active' in form.changed_data and form.cleaned_data['is_active']

    if reactivating and not _locked(membership.organization).has_member_quota():
        raise QuotaExceeded('Limite de usuários do plano atingido.')

    return form.save()
