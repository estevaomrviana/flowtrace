from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.testing import make_member, make_organization

from .models import Membership

User = get_user_model()


def new_member_data(**overrides):
    data = {
        'first_name': 'Ana', 'last_name': 'Lima', 'email': 'ana@provedor.com', 'username': 'ana',
        'role': 'operator', 'password1': 'Sup3r-Segura-123', 'password2': 'Sup3r-Segura-123',
    }
    data.update(overrides)
    return data


class MemberManagementTests(TestCase):

    def setUp(self):
        self.org = make_organization(max_members=2)
        self.admin = make_member(self.org, role='admin', first_name='Admin', email='a@x.com')
        self.client.force_login(self.admin)

    def test_admin_creates_member_in_own_organization(self):
        response = self.client.post(reverse('organizations:member_create'), new_member_data())
        self.assertRedirects(response, reverse('organizations:members'))

        membership = Membership.objects.get(user__username='ana')
        self.assertEqual(membership.organization, self.org)
        self.assertEqual(membership.role, 'operator')
        self.assertTrue(membership.user.check_password('Sup3r-Segura-123'))

    def test_member_quota(self):
        make_member(self.org)  # 2/2
        self.client.post(reverse('organizations:member_create'), new_member_data())
        self.assertFalse(User.objects.filter(username='ana').exists())

    def test_reactivation_respects_quota(self):
        inactive = make_member(self.org, first_name='B', email='b@x.com', is_active=False)
        make_member(self.org)  # 2/2 ativos
        target = inactive.membership
        response = self.client.post(reverse('organizations:member_update', args=[target.pk]), {
            'first_name': 'B', 'email': 'b@x.com', 'is_active': 'on', 'role': 'operator',
        })
        self.assertEqual(response.status_code, 200)
        inactive.refresh_from_db()
        self.assertFalse(inactive.is_active)

    def test_admin_cannot_demote_or_deactivate_self(self):
        mine = self.admin.membership
        self.client.post(reverse('organizations:member_update', args=[mine.pk]), {
            'first_name': 'Admin', 'email': 'a@x.com', 'role': 'operator',
        })
        mine.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertEqual(mine.role, 'admin')
        self.assertTrue(self.admin.is_active)

    def test_reset_member_password(self):
        user = make_member(self.org, first_name='C', email='c@x.com')
        self.client.post(reverse('organizations:member_update', args=[user.membership.pk]), {
            'first_name': 'C', 'email': 'c@x.com', 'is_active': 'on', 'role': 'operator',
            'new_password': 'Outra-Senha-987',
        })
        user.refresh_from_db()
        self.assertTrue(user.check_password('Outra-Senha-987'))

    def test_cannot_edit_member_of_other_organization(self):
        stranger = make_member(make_organization())
        url = reverse('organizations:member_update', args=[stranger.membership.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_operator_has_no_access(self):
        self.client.force_login(make_member(self.org))
        for name in ('detail', 'members', 'member_create'):
            self.assertEqual(self.client.get(reverse(f'organizations:{name}')).status_code, 403)

    def test_pages_render(self):
        for name in ('detail', 'members', 'member_create'):
            self.assertEqual(self.client.get(reverse(f'organizations:{name}')).status_code, 200)
