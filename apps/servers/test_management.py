from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.core.testing import make_member, make_organization, make_server

from .forms import ServerForm
from .models import Server, ServerCredential
from .services.health import check_server
from .services.ssh_client import CommandResult, load_private_key


def openssh_key():
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption(),
    ).decode()


def server_data(**overrides):
    data = {
        'name': 'CGNAT Norte', 'host': '10.0.0.5', 'port': 22, 'log_path': '/var/cache/nfdump',
        'is_active': 'on', 'username': 'nf', 'auth_method': 'password', 'password': 'abc123',
    }
    data.update(overrides)
    return data


class PrivateKeyTests(SimpleTestCase):

    def test_loads_openssh_key(self):
        self.assertEqual(load_private_key(openssh_key()).get_name(), 'ssh-ed25519')

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            load_private_key('não é uma chave')


class ServerFormTests(TestCase):

    def setUp(self):
        self.org = make_organization()

    def test_secrets_are_never_rendered(self):
        server = make_server(self.org, password='nao-pode-vazar')
        html = ServerForm(instance=server).as_div()
        self.assertNotIn('nao-pode-vazar', html)

    def test_blank_password_keeps_saved_one(self):
        server = make_server(self.org, password='original')
        form = ServerForm(server_data(name=server.name, password=''), instance=server)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(ServerCredential.objects.get(server=server).password.reveal(), 'original')

    def test_password_required_on_create(self):
        form = ServerForm(server_data(password=''))
        self.assertIn('password', form.errors)

    def test_switching_to_key_drops_password_and_validates_key(self):
        server = make_server(self.org, password='original')

        invalid = ServerForm(server_data(auth_method='key', private_key='lixo'), instance=server)
        self.assertIn('private_key', invalid.errors)

        form = ServerForm(server_data(auth_method='key', private_key=openssh_key(), password=''), instance=server)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        credential = ServerCredential.objects.get(server=server)
        self.assertEqual(credential.auth_method, 'key')
        self.assertFalse(credential.password)
        self.assertTrue(credential.private_key)

    def test_changing_host_resets_pinned_host_key(self):
        server = make_server(self.org)
        server.credential.remember_host_key('ssh-ed25519 AAAA')
        form = ServerForm(server_data(name=server.name, host='10.9.9.9', password=''), instance=server)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(ServerCredential.objects.get(server=server).host_key, '')

    def test_rejects_relative_log_path_and_bad_host(self):
        form = ServerForm(server_data(log_path='logs', host='a b;rm'))
        self.assertIn('log_path', form.errors)
        self.assertIn('host', form.errors)


class ServerManagementViewTests(TestCase):

    def setUp(self):
        self.org = make_organization(can_manage_servers=True, max_servers=2)
        self.admin = make_member(self.org, role='admin')
        self.operator = make_member(self.org)
        self.client.force_login(self.admin)

    def test_admin_creates_server(self):
        response = self.client.post(reverse('servers:create'), server_data())
        self.assertRedirects(response, reverse('servers:manage'))

        server = Server.objects.get()
        self.assertEqual(server.organization, self.org)
        self.assertEqual(server.created_by, self.admin)
        self.assertFalse(server.managed_by_platform)
        self.assertEqual(server.credential.password.reveal(), 'abc123')

    def test_quota_blocks_new_servers(self):
        make_server(self.org)
        make_server(self.org)
        response = self.client.post(reverse('servers:create'), server_data())
        self.assertRedirects(response, reverse('servers:manage'))
        self.assertEqual(Server.objects.count(), 2)

    def test_operator_cannot_manage(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('servers:manage')).status_code, 403)
        self.assertEqual(self.client.get(reverse('servers:create')).status_code, 403)

    def test_org_without_permission_cannot_create(self):
        self.org.can_manage_servers = False
        self.org.save()
        self.assertEqual(self.client.get(reverse('servers:create')).status_code, 403)
        # Ainda vê a lista (servidores cadastrados pela plataforma).
        self.assertEqual(self.client.get(reverse('servers:manage')).status_code, 200)

    def test_platform_managed_server_is_read_only(self):
        server = make_server(self.org, managed_by_platform=True)
        self.assertEqual(self.client.get(reverse('servers:update', args=[server.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('servers:delete', args=[server.pk])).status_code, 404)
        self.assertTrue(Server.objects.filter(pk=server.pk).exists())

    def test_cannot_touch_other_organization(self):
        other = make_server(make_organization(can_manage_servers=True))
        for name in ('update', 'delete'):
            self.assertEqual(self.client.get(reverse(f'servers:{name}', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('servers:test', args=[other.pk])).status_code, 404)

    def test_manage_list_never_shows_secrets(self):
        make_server(self.org, password='segredo-da-lista')
        response = self.client.get(reverse('servers:manage'))
        self.assertNotContains(response, 'segredo-da-lista')

    def test_delete(self):
        server = make_server(self.org)
        self.client.post(reverse('servers:delete', args=[server.pk]))
        self.assertFalse(Server.objects.exists())
        self.assertFalse(ServerCredential.objects.exists())


class FakeSSH:
    def __init__(self, exit_status):
        self.exit_status = exit_status

    def __call__(self, server):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def run(self, command):
        return CommandResult(self.exit_status, '', '')


class HealthCheckTests(SimpleTestCase):

    def test_reports(self):
        server = Server(name='x', host='h', log_path='/logs')
        self.assertTrue(check_server(server, FakeSSH(0)).ok)
        self.assertIn('nfdump', check_server(server, FakeSSH(10)).message)
        self.assertIn('/logs', check_server(server, FakeSSH(11)).message)


class AdminTests(TestCase):

    def test_admin_change_form_does_not_leak_password(self):
        from django.contrib.auth import get_user_model
        staff = get_user_model().objects.create_superuser('root', 'r@x.com', 'x')
        self.client.force_login(staff)
        server = make_server(make_organization(), password='senha-admin')

        response = self.client.get(reverse('admin:servers_server_change', args=[server.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'senha-admin')

    def test_admin_creates_platform_managed_server(self):
        from django.contrib.auth import get_user_model
        staff = get_user_model().objects.create_superuser('root', 'r@x.com', 'x')
        self.client.force_login(staff)
        org = make_organization()

        response = self.client.post(
            reverse('admin:servers_server_add'),
            server_data(organization=org.pk, managed_by_platform='on'),
        )
        self.assertEqual(response.status_code, 302)
        server = Server.objects.get()
        self.assertTrue(server.managed_by_platform)
        self.assertEqual(server.credential.password.reveal(), 'abc123')
