from django.core.exceptions import ValidationError
from django.core.validators import validate_ipv46_address
from django.utils.http import urlencode
from django.views.generic import ListView

from apps.organizations.mixins import OrganizationMemberMixin

from .models import SearchLog


class SearchLogListView(OrganizationMemberMixin, ListView):
    template_name = 'audit/searchlog_list.html'
    context_object_name = 'logs'
    paginate_by = 30

    def get_queryset(self):
        qs = SearchLog.objects.visible_to(self.membership)
        ip = self.request.GET.get('ip', '').strip()
        if ip:
            qs = qs.filter(query_ip=ip) if _is_ip(ip) else qs.none()
        return qs

    def get_context_data(self, **kwargs):
        ip = self.request.GET.get('ip', '').strip()
        return super().get_context_data(
            ip_filter=ip, querystring=urlencode({'ip': ip}) if ip else '', **kwargs,
        )


def _is_ip(value):
    try:
        validate_ipv46_address(value)
        return True
    except ValidationError:
        return False
