import socket
import threading
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.core.testing import make_member, make_organization, make_server, raw_column
from apps.servers.services.exceptions import ServerConnectionError
from apps.servers.services.ssh_tunnel import SSHTunnel

from .forms import SubscriberSourceForm
from .models import SubscriberSource
from .services import SubscriberLookup, SubscriberSourceError, check_source

AT = datetime(2026, 3, 17, 16, 40, 0)


def session_row(ip='100.64.0.10', login='joao', start=datetime(2026, 3, 17, 8, 0), stop=None, **extra):
    return {
        'username': login, 'framedipaddress': ip, 'acctstarttime': start, 'acctstoptime': stop,
        'callingstationid': 'AA:BB:CC:00:11:22', 'nasipaddress': '10.1.1.1', 'acctsessionid': 'x1', **extra,
    }


class FakeCursor:

    def __init__(self, db):
        self.db = db
        self.description = None
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def execute(self, sql, params):
        self.db.queries.append((sql, params))
        rows = self.db.answer(sql, params)
        columns = list(rows[0]) if rows else ['x']
        self.description = [(c, None, None, None, None, None, None) for c in columns]
        self._rows = [tuple(r.values()) for r in rows]

    def fetchall(self):
        return self._rows


class FakeDB:
    """Simula o radacct: responde às consultas de sessão, de cadastro e de teste."""

    def __init__(self, sessions=(), customers=None, fail=None):
        self.sessions = list(sessions)
        self.customers = customers or {}
        self.fail = fail
        self.queries = []

    def answer(self, sql, params):
        if self.fail:
            raise RuntimeError(self.fail)
        if 'framedipaddress =' in sql:
            rows = [s for s in self.sessions if s['framedipaddress'] == params['ip']
                    and s['acctstarttime'] <= self._as_column(params['at'], s['acctstarttime'])]
            return sorted(rows, key=lambda s: s['acctstarttime'], reverse=True)[:1]
        if sql.startswith('SELECT username, acctstarttime'):
            rows = sorted(self.sessions, key=lambda s: s['acctstarttime'], reverse=True)[:1]
            return [{'username': r['username'], 'acctstarttime': r['acctstarttime']} for r in rows]
        customer = self.customers.get(params.get('login'))
        return [customer] if customer else []

    @staticmethod
    def _as_column(value, column):
        # Como o PostgreSQL: parâmetro sem fuso vale no fuso da sessão (o da fonte).
        if column.tzinfo is not None and value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo('America/Fortaleza'))
        return value

    def cursor(self):
        return FakeCursor(self)

    def connector(self, source):
        @contextmanager
        def _connect():
            yield self
        return _connect()


def make_source(**kwargs):
    kwargs.setdefault('name', 'radius')
    kwargs.setdefault('table', 'radacct')
    kwargs.setdefault('timezone', 'America/Fortaleza')
    return SubscriberSource(**kwargs)


class LookupTests(SimpleTestCase):

    def lookup(self, db, **source):
        return SubscriberLookup([make_source(**source)], connector=db.connector)

    def test_open_session_identifies_subscriber_with_customer_data(self):
        db = FakeDB([session_row()], customers={'joao': {'nome': 'João da Silva', 'documento': '123'}})
        result = self.lookup(db, customer_query='SELECT nome FROM c WHERE login = %(login)s').find(
            ['100.64.0.10'], AT, 'America/Fortaleza')

        [session] = result.for_ip('100.64.0.10')
        self.assertEqual(session.login, 'joao')
        self.assertTrue(session.is_open)
        self.assertEqual(session.customer, {'nome': 'João da Silva', 'documento': '123'})
        self.assertEqual(session.mac, 'AA:BB:CC:00:11:22')
        self.assertEqual(result.errors, [])

    def test_session_closed_before_the_moment_is_ignored(self):
        db = FakeDB([session_row(stop=datetime(2026, 3, 17, 12, 0))])
        result = self.lookup(db).find(['100.64.0.10'], AT, 'America/Fortaleza')
        self.assertEqual(result.for_ip('100.64.0.10'), [])

    def test_only_latest_session_before_the_moment_counts(self):
        db = FakeDB([
            session_row(login='antigo', start=datetime(2026, 3, 1)),  # sem stop: resíduo
            session_row(login='atual', start=datetime(2026, 3, 17, 9), stop=datetime(2026, 3, 17, 20)),
            session_row(login='depois', start=datetime(2026, 3, 17, 21)),
        ])
        [session] = self.lookup(db).find(['100.64.0.10'], AT, 'America/Fortaleza').for_ip('100.64.0.10')
        self.assertEqual(session.login, 'atual')
        self.assertEqual(session.stopped_at, datetime(2026, 3, 17, 20))

    def test_converts_moment_to_source_timezone_and_back(self):
        db = FakeDB([session_row(start=datetime(2026, 3, 17, 19, 0))])  # radacct em UTC
        lookup = self.lookup(db, timezone='UTC')

        [session] = lookup.find(['100.64.0.10'], datetime(2026, 3, 17, 16, 30), 'America/Fortaleza').for_ip('100.64.0.10')

        self.assertEqual(db.queries[0][1]['at'], datetime(2026, 3, 17, 19, 30))
        self.assertEqual(session.started_at, datetime(2026, 3, 17, 16, 0))

    def test_timestamptz_values_are_converted_not_truncated(self):
        # PostgreSQL devolve timestamptz com fuso; 11:00 UTC = 08:00 em Fortaleza.
        utc = ZoneInfo('UTC')
        db = FakeDB([session_row(start=datetime(2026, 3, 17, 11, 0, tzinfo=utc),
                                 stop=datetime(2026, 3, 17, 23, 0, tzinfo=utc))])
        [session] = self.lookup(db).find(['100.64.0.10'], AT, 'America/Fortaleza').for_ip('100.64.0.10')
        self.assertEqual(session.started_at, datetime(2026, 3, 17, 8, 0))
        self.assertEqual(session.stopped_at, datetime(2026, 3, 17, 20, 0))

        # 20:30 em Fortaleza = 23:30 UTC: a sessão já tinha terminado.
        later = self.lookup(db).find(['100.64.0.10'], datetime(2026, 3, 17, 20, 30), 'America/Fortaleza')
        self.assertEqual(later.for_ip('100.64.0.10'), [])

    def test_mysql_zero_date_is_treated_as_open(self):
        db = FakeDB([session_row(stop='0000-00-00 00:00:00')])
        [session] = self.lookup(db).find(['100.64.0.10'], AT, 'America/Fortaleza').for_ip('100.64.0.10')
        self.assertTrue(session.is_open)

    def test_failing_source_becomes_error_message(self):
        def broken(source):
            raise SubscriberSourceError('Access denied')

        result = SubscriberLookup([make_source()], connector=broken).find(['100.64.0.10'], AT, 'UTC')
        self.assertEqual(result.sessions, {})
        self.assertEqual(result.errors, ['radius: Access denied'])

    def test_sql_failure_becomes_error_message(self):
        result = self.lookup(FakeDB(fail="Table 'radacct' doesn't exist")).find(['100.64.0.10'], AT, 'UTC')
        self.assertIn("doesn't exist", result.errors[0])

    def test_session_roundtrip(self):
        db = FakeDB([session_row()])
        [session] = self.lookup(db).find(['100.64.0.10'], AT, 'America/Fortaleza').for_ip('100.64.0.10')
        self.assertEqual(type(session).from_dict(session.to_dict()), session)

    def test_check_source_reports_latest_session(self):
        db = FakeDB([session_row()], customers={'joao': {'nome': 'João'}})
        report = check_source(make_source(customer_query='SELECT ... %(login)s'), connector=db.connector)
        self.assertTrue(report.ok)
        self.assertIn('17/03/2026 08:00', report.message)
        self.assertIn('Consulta de cadastro OK (1 campos)', report.message)
        self.assertNotIn('João', report.message)


class EchoServer:
    """Servidor TCP local que devolve o que recebe (faz o papel do banco)."""

    def __init__(self):
        self.sock = socket.create_server(('127.0.0.1', 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            while data := conn.recv(1024):
                conn.sendall(data)


class FakeTunnelSSH:
    """O canal 'direct-tcpip' do paramiko é um objeto tipo socket; aqui é um socket real."""

    def __init__(self, port=None, error=None):
        self.port = port
        self.error = error

    def open_direct_channel(self, host, port):
        if self.error:
            raise ServerConnectionError(self.error)
        return socket.create_connection(('127.0.0.1', self.port))


class SSHTunnelTests(SimpleTestCase):

    def test_forwards_bytes_both_ways(self):
        echo = EchoServer()
        with SSHTunnel(FakeTunnelSSH(echo.port), 'db.interno', 3306) as port:
            with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                client.sendall(b'SELECT 1')
                self.assertEqual(client.recv(1024), b'SELECT 1')

    def test_unreachable_destination_fails_before_returning_port(self):
        with self.assertRaises(ServerConnectionError):
            with SSHTunnel(FakeTunnelSSH(error='Connection refused'), 'db.interno', 3306):
                pass


class SourceFormTests(TestCase):

    def setUp(self):
        self.org = make_organization()
        self.server = make_server(self.org)

    def data(self, **overrides):
        data = {
            'name': 'RADIUS', 'engine': 'mysql', 'connection': 'ssh', 'ssh_server': self.server.pk,
            'db_host': '127.0.0.1', 'db_port': 3306, 'db_name': 'radius', 'db_user': 'leitura',
            'db_password': 'segredo', 'table': 'radacct', 'timezone': 'America/Fortaleza',
            'customer_query': '', 'is_active': 'on',
        }
        data.update(overrides)
        return data

    def test_valid_and_password_is_encrypted(self):
        form = SubscriberSourceForm(self.data(), organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        source = form.save(organization=self.org)
        self.assertEqual(source.db_password.reveal(), 'segredo')
        raw = raw_column(SubscriberSource, 'db_password', source.pk)
        self.assertNotIn('segredo', raw)

    def test_customer_query_rules(self):
        cases = {
            'DELETE FROM sis_cliente WHERE login = %(login)s': 'SELECT',
            'SELECT nome FROM c WHERE login = %(login)s; DROP TABLE c': 'ponto e vírgula',
            "SELECT nome FROM c WHERE login = 'x'": '%(login)s',
        }
        for query, message in cases.items():
            form = SubscriberSourceForm(self.data(customer_query=query), organization=self.org)
            self.assertFalse(form.is_valid())
            self.assertIn(message, str(form.errors['customer_query']))

        form = SubscriberSourceForm(
            self.data(customer_query='SELECT nome FROM c WHERE login = %(login)s;'), organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.cleaned_data['customer_query'].endswith(';'))

    def test_table_name_is_an_identifier(self):
        form = SubscriberSourceForm(self.data(table='radacct; drop'), organization=self.org)
        self.assertIn('table', form.errors)

    def test_tunnel_requires_server_of_same_organization(self):
        other = make_server(make_organization())
        form = SubscriberSourceForm(self.data(ssh_server=other.pk), organization=self.org)
        self.assertIn('ssh_server', form.errors)
        form = SubscriberSourceForm(self.data(ssh_server=''), organization=self.org)
        self.assertIn('ssh_server', form.errors)

    def test_direct_connection_drops_server(self):
        form = SubscriberSourceForm(self.data(connection='direct'), organization=self.org)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save(organization=self.org).ssh_server)


class SourceViewTests(TestCase):

    def setUp(self):
        self.org = make_organization(can_manage_servers=True)
        self.admin = make_member(self.org, role='admin')
        self.operator = make_member(self.org)

    def test_operator_cannot_see_sources(self):
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('subscribers:list')).status_code, 403)

    def test_admin_creates_source(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('subscribers:create'), {
            'name': 'RADIUS', 'engine': 'postgresql', 'connection': 'direct',
            'db_host': 'radius.provedor.net', 'db_port': 5432, 'db_name': 'radius', 'db_user': 'leitura',
            'db_password': 'segredo', 'table': 'radacct', 'timezone': 'UTC', 'is_active': 'on',
        })
        self.assertRedirects(response, reverse('subscribers:list'))
        source = SubscriberSource.objects.get()
        self.assertEqual((source.organization, source.created_by), (self.org, self.admin))
        self.assertContains(self.client.get(reverse('subscribers:list')), 'radius.provedor.net')
