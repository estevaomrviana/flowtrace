from .models import Membership

_CACHE_ATTR = '_cached_membership'


def get_membership(request):
    """Vínculo ativo do usuário logado (ou None), memorizado no request."""
    if not hasattr(request, _CACHE_ATTR):
        membership = None
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            membership = (
                Membership.objects
                .select_related('organization')
                .filter(user=user, organization__is_active=True)
                .first()
            )
        setattr(request, _CACHE_ATTR, membership)
    return getattr(request, _CACHE_ATTR)
