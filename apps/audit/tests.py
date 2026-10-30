from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.testing import make_member, make_organization, make_server

from .models import SearchLog


def log(org, user, server, ip='203.0.113.1'):
    return SearchLog.objects.create(
        organization=org, user=user, username=user.username, server=server, server_name=server.name,
        status=SearchLog.Status.SUCCESS, query_ip=ip, query_datetime=timezone.now(), minute_margin=5,
    )


class SearchLogVisibilityTests(TestCase):

    def setUp(self):
        self.org = make_organization()
        self.admin = make_member(self.org, role='admin')
        self.operator = make_member(self.org)
        self.server = make_server(self.org)

        log(self.org, self.admin, self.server, ip='198.51.100.1')
        log(self.org, self.operator, self.server, ip='198.51.100.2')

        other_org = make_organization()
        log(other_org, make_member(other_org), make_server(other_org), ip='198.51.100.3')

    def ips(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse('audit:list'), params)
        self.assertEqual(response.status_code, 200)
        return sorted(entry.query_ip for entry in response.context['logs'])

    def test_admin_sees_whole_organization_only(self):
        self.assertEqual(self.ips(self.admin), ['198.51.100.1', '198.51.100.2'])

    def test_operator_sees_only_own(self):
        self.assertEqual(self.ips(self.operator), ['198.51.100.2'])

    def test_filter_by_ip(self):
        self.assertEqual(self.ips(self.admin, ip='198.51.100.1'), ['198.51.100.1'])
        self.assertEqual(self.ips(self.admin, ip='lixo'), [])

    def test_log_survives_server_deletion(self):
        self.server.delete()
        entry = SearchLog.objects.filter(organization=self.org).first()
        self.assertIsNone(entry.server)
        self.assertEqual(entry.server_name, self.server.name)
