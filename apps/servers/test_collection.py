import shlex
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.core.testing import make_member, make_organization, make_server

from .models import CollectionStatus, LogFile, Server, validate_local_log_path
from .services import collection
from .services.collection import (
    files_for_window,
    list_command,
    parse_hashes,
    parse_listing,
    sync_server,
    verify_day,
)
from .services.runner import LocalRunner, runner_for
from .services.ssh_client import CommandResult, SSHClient

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=dt_timezone.utc)  # 12:00 em Fortaleza


def fake_hash(path, version=''):
    return (format(abs(hash(path + version)), 'x') * 8)[:64].ljust(64, '0')


class FakeRunner:
    """Simula o servidor: `files` = {caminho relativo: (mtime aware, tamanho)}."""

    def __init__(self, files=None, list_status=0, hashes=None):
        self.files = files or {}
        self.list_status = list_status
        self.hashes = hashes or {}
        self.commands = []

    def __call__(self, server):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def run(self, command):
        self.commands.append(command)
        if 'sha256sum' in command:
            paths = shlex.split(command.split('sha256sum --', 1)[1])
            lines = [f'{self.hashes.get(p, fake_hash(p))}  {p}' for p in paths if p in self.files]
            return CommandResult(0 if len(lines) == len(paths) else 1, '\n'.join(lines), '')
        if self.list_status:
            return CommandResult(self.list_status, '', '')
        lines = [f'{mtime.timestamp():.10f} {size} {path}' for path, (mtime, size) in self.files.items()]
        return CommandResult(0, '\n'.join(lines), '')


def nf(minutes_ago, day='2026/11/18'):
    """Arquivo rotacionado há `minutes_ago` min (nome no horário de Fortaleza, início do intervalo)."""
    mtime = NOW - timedelta(minutes=minutes_ago)
    name = (mtime - timedelta(hours=3, minutes=5)).strftime('%Y%m%d%H%M')
    return f'{day}/nfcapd.{name}', (mtime, 1000 + minutes_ago)


class ParsingTests(SimpleTestCase):

    def test_list_command_quotes_and_filters(self):
        command = list_command('/dados/org a/cisco', [datetime(2026, 11, 17).date(), datetime(2026, 11, 18).date()])
        self.assertIn("cd '/dados/org a/cisco'", command)
        self.assertIn('2026/11/17 2026/11/18', command)
        self.assertIn("-name 'nfcapd.[0-9]*'", command)

    def test_parse_listing_ignores_noise(self):
        files = parse_listing(
            '1763478000.5000000000 1234 2026/11/18/nfcapd.202611181155\n'
            '1763478000.5 99 2026/11/18/nfcapd.current.1234\n'
            'lixo\n'
            '1763478000 10 ../../etc/passwd\n'
        )
        self.assertEqual([f.path for f in files], ['2026/11/18/nfcapd.202611181155'])
        self.assertEqual(files[0].size, 1234)

    def test_parse_hashes(self):
        h = 'a' * 64
        self.assertEqual(parse_hashes(f'{h}  2026/11/18/nfcapd.202611181155\nsha256sum: x: No such file'),
                         {'2026/11/18/nfcapd.202611181155': h})

    def test_interval_start_uses_server_timezone(self):
        start = collection.interval_start('2026/11/18/nfcapd.202611181155', 'America/Fortaleza')
        self.assertEqual(start.astimezone(dt_timezone.utc), datetime(2026, 11, 18, 14, 55, tzinfo=dt_timezone.utc))


@mock.patch('apps.servers.services.collection.send_alert')
class SyncServerTests(TestCase):

    def setUp(self):
        self.server = make_server(make_organization(), log_path='/var/cache/nfdump')

    def sync(self, runner, now=NOW):
        return sync_server(self.server, now=now, runner_factory=runner)

    def test_receiving_files_is_ok_and_registers_manifest(self, alert):
        runner = FakeRunner(dict([nf(3), nf(8), nf(13, day='2026/11/17')]))
        report = self.sync(runner)

        self.assertEqual(report.state, CollectionStatus.State.OK)
        self.assertEqual(report.registered, 3)
        status = self.server.collection
        self.assertEqual(status.state, 'ok')
        self.assertEqual(status.last_file_at, NOW - timedelta(minutes=3))
        self.assertEqual(LogFile.objects.filter(server=self.server).count(), 3)
        alert.assert_not_called()

        # Segunda passada: nada novo para calcular.
        runner.commands.clear()
        self.assertEqual(self.sync(runner).registered, 0)
        self.assertFalse(any('sha256sum' in c for c in runner.commands))

    def test_file_still_being_written_waits(self, alert):
        path, (mtime, size) = nf(0)
        runner = FakeRunner({path: (NOW - timedelta(seconds=5), size)})
        self.assertEqual(self.sync(runner).registered, 0)
        self.assertFalse(LogFile.objects.exists())

    def test_stale_collection_alerts_once_then_recovers(self, alert):
        runner = FakeRunner(dict([nf(40)]))
        report = self.sync(runner)
        self.assertEqual(report.state, CollectionStatus.State.STALE)
        self.assertIn('40 min', report.message)
        alert.assert_called_once()
        self.assertIn('atrasada', alert.call_args.args[0])

        # Continua parada 10 min depois: não repete o alerta.
        self.sync(runner, now=NOW + timedelta(minutes=10))
        alert.assert_called_once()
        self.assertEqual(self.server.collection.problem_since, NOW)

        # Depois do intervalo de realerta, avisa de novo.
        self.sync(runner, now=NOW + timedelta(hours=7))
        self.assertEqual(alert.call_count, 2)

        # Voltou a chegar arquivo: avisa que normalizou e limpa o problema.
        runner.files.update(dict([nf(-7 * 60 + 2)]))
        self.sync(runner, now=NOW + timedelta(hours=7))
        self.assertEqual(alert.call_count, 3)
        self.assertIn('normalizada', alert.call_args.args[0])
        status = CollectionStatus.objects.get(server=self.server)
        self.assertEqual(status.state, 'ok')
        self.assertIsNone(status.problem_since)
        self.assertIsNone(status.alerted_at)

    def test_unmonitored_server_does_not_alert(self, alert):
        self.server.monitor_collection = False
        self.server.save()
        self.assertEqual(self.sync(FakeRunner({})).state, CollectionStatus.State.EMPTY)
        alert.assert_not_called()

    def test_missing_folder_is_error(self, alert):
        report = self.sync(FakeRunner(list_status=collection.BASE_MISSING_EXIT))
        self.assertEqual(report.state, CollectionStatus.State.ERROR)
        self.assertIn('/var/cache/nfdump', report.message)

    def test_connection_failure_is_error_without_exception(self, alert):
        from .services.exceptions import ServerConnectionError

        def broken(server):
            raise ServerConnectionError('Falha ao conectar em 10.0.0.1:22: timeout')

        report = self.sync(broken)
        self.assertEqual(report.state, CollectionStatus.State.ERROR)
        self.assertIn('timeout', self.server.collection.message)

    def test_changed_file_is_flagged(self, alert):
        path, (mtime, size) = nf(10)
        runner = FakeRunner({path: (mtime, size)})
        self.sync(runner)
        runner.files[path] = (mtime + timedelta(minutes=1), size + 50)
        report = self.sync(runner, now=NOW + timedelta(minutes=2))
        self.assertEqual(report.changed, [path])
        self.assertIsNotNone(LogFile.objects.get(path=path).changed_at)
        self.assertIn('alterado', alert.call_args.args[0])

    def test_verify_day_detects_tampering_and_missing_files(self, alert):
        files = dict([nf(10), nf(15)])
        runner = FakeRunner(files)
        self.sync(runner)
        (a, _), (b, _) = sorted(files.items())

        runner.hashes[a] = 'f' * 64
        del runner.files[b]
        report = verify_day(self.server, datetime(2026, 11, 18).date(), runner_factory=runner)
        self.assertEqual(report.checked, 2)
        self.assertEqual(report.mismatched, [a])
        self.assertEqual(report.missing, [b])
        self.assertFalse(report.ok)

    def test_files_for_window(self, alert):
        names = ['202611181145', '202611181150', '202611181155', '202611181200', '202611181210']
        runner = FakeRunner({f'2026/11/18/nfcapd.{n}': (NOW - timedelta(minutes=30), 10) for n in names})
        self.sync(runner)
        window = files_for_window(
            self.server, datetime(2026, 11, 18, 11, 56), datetime(2026, 11, 18, 12, 4), 'America/Fortaleza',
        )
        self.assertEqual([f.path[-12:] for f in window], ['202611181155', '202611181200'])


class CheckCollectionCommandTests(TestCase):

    @mock.patch('apps.servers.management.commands.check_collection.ping_healthcheck')
    @mock.patch('apps.servers.services.collection.send_alert')
    def test_runs_every_active_server_and_pings(self, alert, ping):
        org = make_organization()
        active = make_server(org)
        make_server(org, is_active=False)
        runner = FakeRunner(dict([nf(2)]))
        with mock.patch('apps.servers.services.collection.runner_for', runner):
            out, err = StringIO(), StringIO()
            call_command('check_collection', stdout=out, stderr=err)
        # Os arquivos são de NOW; conforme o relógio real, a linha vai para stdout ou stderr.
        self.assertIn(active.name, out.getvalue() + err.getvalue())
        self.assertEqual(CollectionStatus.objects.count(), 1)
        ping.assert_called_once()


class LocalRunnerTests(SimpleTestCase):

    def test_runner_for_picks_by_access(self):
        self.assertIsInstance(runner_for(Server(access=Server.Access.LOCAL)), LocalRunner)
        sentinel = object()
        self.assertIs(runner_for(Server(access=Server.Access.SSH), ssh_factory=lambda s: sentinel), sentinel)
        self.assertIs(runner_for.__defaults__[0], SSHClient)

    @mock.patch('apps.servers.services.runner.subprocess.run')
    def test_runs_with_shell_and_timeout(self, run):
        run.return_value = mock.Mock(returncode=3, stdout=b'out', stderr='erro'.encode())
        with LocalRunner(Server(access='local'), command_timeout=7) as runner:
            result = runner.run('nfdump -R x')
        self.assertEqual(result, CommandResult(3, 'out', 'erro'))
        self.assertEqual(run.call_args.args[0], ['/bin/sh', '-c', 'nfdump -R x'])
        self.assertEqual(run.call_args.kwargs['timeout'], 7)

    @mock.patch('apps.servers.services.runner.subprocess.run')
    def test_timeout_becomes_command_error(self, run):
        import subprocess

        from .services.exceptions import RemoteCommandError
        run.side_effect = subprocess.TimeoutExpired('sh', 1)
        with self.assertRaises(RemoteCommandError):
            LocalRunner(Server(access='local')).run('sleep 9')


class LocalServerValidationTests(TestCase):

    @override_settings(FLOWTRACE_DATA_ROOT='')
    def test_local_mode_disabled_without_data_root(self):
        with self.assertRaises(ValidationError):
            validate_local_log_path('/dados/org/cisco')

    @override_settings(FLOWTRACE_DATA_ROOT='/dados')
    def test_path_must_stay_inside_data_root(self):
        validate_local_log_path('/dados/org/cisco')
        for bad in ('/dados', '/etc', '/dados/../etc', '/dadosx/org', 'dados/org'):
            with self.subTest(bad), self.assertRaises(ValidationError):
                validate_local_log_path(bad)

    @override_settings(FLOWTRACE_DATA_ROOT='/dados')
    def test_admin_creates_local_server_without_credential(self):
        staff = get_user_model().objects.create_superuser('root', 'r@x.com', 'x')
        self.client.force_login(staff)
        org = make_organization()
        response = self.client.post(reverse('admin:servers_server_add'), {
            'organization': org.pk, 'name': 'Cisco central', 'access': 'local', 'host': 'localhost',
            'port': 22, 'log_path': '/dados/org/cisco', 'timezone': 'America/Fortaleza',
            'is_active': 'on', 'monitor_collection': 'on',
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['adminform'].form.errors)
        server = Server.objects.get()
        self.assertTrue(server.is_local)
        self.assertTrue(server.managed_by_platform)
        self.assertFalse(hasattr(server, 'credential') and server.credential.pk)

    @override_settings(FLOWTRACE_DATA_ROOT='/dados')
    def test_admin_rejects_local_server_outside_data_root(self):
        staff = get_user_model().objects.create_superuser('root', 'r@x.com', 'x')
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:servers_server_add'), {
            'organization': make_organization().pk, 'name': 'X', 'access': 'local', 'host': 'localhost',
            'port': 22, 'log_path': '/etc', 'timezone': 'America/Fortaleza', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Server.objects.exists())

    def test_admin_still_requires_ssh_user_for_ssh_servers(self):
        staff = get_user_model().objects.create_superuser('root', 'r@x.com', 'x')
        self.client.force_login(staff)
        response = self.client.post(reverse('admin:servers_server_add'), {
            'organization': make_organization().pk, 'name': 'X', 'access': 'ssh', 'host': '10.0.0.1',
            'port': 22, 'log_path': '/logs', 'timezone': 'America/Fortaleza', 'is_active': 'on',
            'auth_method': 'password', 'password': 'x',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Server.objects.exists())


@mock.patch('apps.servers.services.collection.send_alert')
class CollectionViewsTests(TestCase):

    def test_manage_list_shows_collection_state(self, alert):
        org = make_organization()
        admin = make_member(org, role='admin')
        server = make_server(org)
        sync_server(server, now=NOW, runner_factory=FakeRunner(dict([nf(50)])))
        self.client.force_login(admin)
        response = self.client.get(reverse('servers:manage'))
        self.assertContains(response, 'Último registro há')
        self.assertContains(response, 'ft-badge--near')

    def test_test_button_also_checks_collection(self, alert):
        org = make_organization()
        admin = make_member(org, role='admin')
        server = make_server(org)
        self.client.force_login(admin)
        runner = FakeRunner(dict([nf(2)]))
        # check_server roda `command -v nfdump; test -d` e recebe status 0 do FakeRunner.
        with mock.patch('apps.servers.services.health.runner_for', runner), \
                mock.patch('apps.servers.services.collection.runner_for', runner):
            response = self.client.post(reverse('servers:test', args=[server.pk]), follow=True)
        self.assertContains(response, 'Coleta: Último arquivo recebido há')
        self.assertTrue(CollectionStatus.objects.filter(server=server).exists())
