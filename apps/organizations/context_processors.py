from .utils import get_membership


def organization(request):
    membership = get_membership(request)
    return {
        'membership': membership,
        'organization': membership.organization if membership else None,
    }
