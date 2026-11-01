import json
from datetime import datetime, timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.audit.models import SearchLog
from apps.core.testing import make_member, make_organization, make_server, raw_column
from apps.servers.services.ssh_client import CommandResult
from apps.servers.tests import FakeSSH, flow
from apps.subscribers.services import SubscriberLookup
from apps.subscribers.tests import FakeDB, make_source, session_row

from .models import Case, CaseItem, CaseReport
from .parsing import parse_lines
from .services import ItemResult, content_hash

FORTALEZA = ZoneInfo('America/Fortaleza')


class ParsingTests(SimpleTestCase):

    def parse(self, text, tz='America/Fortaleza'):
        return parse_lines(text, tz)

    def test_accepted_formats(self):
        parsed, errors = self.parse(
            "IP;Data;Porta\n"
            "203.0.113.1;17/03/2026 16:40:00;51234\n"
            "203.0.113.1:51234;2026-03-17 16:40\n"
            "198.51.100.7\t2026-03-17T16:40:05\n"
            "# comentário\n"
            "\n"
            "198.51.100.8 , 17/03/2026 16:40:05 , \n"
        )
        self.assertEqual(errors, [])
        self.assertEqual([(p.ip, p.port) for p in parsed], [
            ('203.0.113.1', 51234), ('203.0.113.1', 51234), ('198.51.100.7', None), ('198.51.100.8', None),
        ])
        self.assertEqual(parsed[0].moment, datetime(2026, 3, 17, 16, 40, tzinfo=FORTALEZA))
        self.assertEqual(parsed[0].timezone, 'America/Fortaleza')
        self.assertEqual(parsed[0].line, 2)

    def test_timezone_in_the_line_wins(self):
        parsed, _ = self.parse(
            "203.0.113.1;2026-03-17 19:40:00 UTC\n"
            "203.0.113.1;2026-03-17T19:40:00Z\n"
            "203.0.113.1;2026-03-17T16:40:00-03:00\n"
        )
        expected = datetime(2026, 3, 17, 19, 40, tzinfo=dt_timezone.utc)
        self.assertEqual([p.moment for p in parsed], [expected] * 3)
        self.assertEqual([p.timezone for p in parsed], ['UTC', 'UTC', 'America/Fortaleza'])

    def test_errors_point_to_the_line(self):
        _, errors = self.parse(
            "203.0.113.1;17/03/2026 16:40:00\n"
            "999.0.113.1;17/03/2026 16:40:00\n"
            "203.0.113.1;17/03/2026\n"
            "203.0.113.1;31/02/2026 10:00:00\n"
            "203.0.113.1:80;17/03/2026 16:40:00;443\n"
            "203.0.113.1;17/03/2026 16:40:00;70000\n"
        )
        self.assertEqual([e.line for e in errors], [2, 3, 4, 5, 6])
        self.assertIn('IP inválido', errors[0].message)
        self.assertIn('hora', errors[1].message)


def result_data(records, sessions=None, has_sources=True):
    return {
        'server': 'cgnat', 'log_tz': 'America/Fortaleza', 'target': '2026-03-17T16:40:00',
        'window': ['2026-03-17T16:35:00', '2026-03-17T16:45:00'], 'days_missing': [],
        'records': [
            {'source_ip': ip, 'flow_time': f'2026-03-17T16:{minute}', 'delta_seconds': delta,
             'port_block_start': 1024, 'port_block_end': 1535, 'translated_port': None}
            for ip, minute, delta in records
        ],
        'has_sources': has_sources,
        'sessions': sessions or {},
        'subscriber_errors': [],
    }


def session(login, ip='100.64.0.10'):
    return {'source': 'radius', 'login': login, 'ip': ip, 'started_at': '2026-03-17T08:00:00',
            'stopped_at': None, 'mac': '', 'nas_ip': '', 'session_id': '', 'customer': {}}


class ConclusionTests(SimpleTestCase):

    def conclude(self, *args, **kwargs):
        return ItemResult.from_data(result_data(*args, **kwargs)).conclusion

    def test_identified(self):
        c = self.conclude([('100.64.0.10', '40:10', 10), ('100.64.0.99', '43:00', 180)],
                          {'100.64.0.10': [session('joao')]})
        self.assertEqual(c.kind, 'identified')
        self.assertEqual([s.login for s in c.sessions], ['joao'])

    def test_two_private_ips_in_the_exact_window_is_ambiguous(self):
        c = self.conclude([('100.64.0.10', '40:10', 10), ('100.64.0.11', '40:20', 20)],
                          {'100.64.0.10': [session('joao')], '100.64.0.11': [session('maria', '100.64.0.11')]})
        self.assertEqual(c.kind, 'ambiguous')
        self.assertEqual(len(c.sessions), 2)

    def test_private_ip_without_session(self):
        self.assertEqual(self.conclude([('100.64.0.10', '40:10', 10)]).kind, 'unmatched')

    def test_without_sources_reports_private_ip(self):
        c = self.conclude([('100.64.0.10', '40:10', 10)], has_sources=False)
        self.assertEqual((c.kind, c.private_ips), ('private_only', ['100.64.0.10']))

    def test_near_only_and_empty(self):
        self.assertEqual(self.conclude([('100.64.0.10', '43:00', 180)]).kind, 'near_only')
        self.assertEqual(self.conclude([]).kind, 'not_found')


class CaseFlowTests(TestCase):

    def setUp(self):
        self.org = make_organization(name='Provedor Exemplo', document='12.345.678/0001-90')
        self.user = make_member(self.org, first_name='Ana', last_name='Lima')
        self.server = make_server(self.org, timezone='America/Fortaleza')
        self.client.force_login(self.user)

    def open_case(self, **kwargs):
        response = self.client.post(reverse('cases:create'), {
            'number': '0801234-56.2026.8.06.0001', 'authority_type': 'judiciary',
            'authority': '2ª Vara Criminal de Fortaleza', 'kind': 'court_order',
            'received_on': '2026-03-20', 'deadline': '2026-03-30', **kwargs,
        })
        case = Case.objects.latest('pk')
        self.assertRedirects(response, reverse('cases:detail', args=[case.pk]))
        return case

    def add(self, case, lines, tz='UTC'):
        return self.client.post(reverse('cases:detail', args=[case.pk]), {
            'server': self.server.pk, 'timezone': tz, 'minute_margin': 5, 'lines': lines,
        })

    def fakes(self, nfdump_records, sessions=()):
        ssh = FakeSSH({'2026/03/17': CommandResult(0, json.dumps(nfdump_records), '')})
        db = FakeDB(sessions, customers={'joao': {'nome': 'João da Silva', 'cpf': '111.222.333-44'}})
        lookup = SubscriberLookup([make_source(customer_query='SELECT %(login)s')], connector=db.connector)
        return (
            mock.patch('apps.servers.services.flow_service.SSHClient', ssh),
            mock.patch('apps.cases.services.SubscriberLookup.for_organization', return_value=lookup),
            ssh,
        )

    def test_full_flow_batch_run_and_pdf(self):
        case = self.open_case()
        response = self.add(case, '203.0.113.1:1100;2026-03-17 19:40:00\n203.0.113.1;17/03/2026 19:40:00;1100')
        self.assertRedirects(response, reverse('cases:detail', args=[case.pk]))
        first, second = case.items.all()
        self.assertEqual((first.position, second.position), (1, 2))
        self.assertEqual(first.input_timezone, 'UTC')
        self.assertEqual(first.informed, datetime(2026, 3, 17, 19, 40))

        # Com consulta pendente o PDF é bloqueado.
        response = self.client.post(reverse('cases:report', args=[case.pk]))
        self.assertRedirects(response, reverse('cases:detail', args=[case.pk]))
        self.assertFalse(CaseReport.objects.exists())

        ssh_patch, lookup_patch, ssh = self.fakes([flow('2026-03-17T16:40:05')], [session_row()])
        with ssh_patch, lookup_patch:
            for item in (first, second):
                response = self.client.post(
                    reverse('cases:item_run', args=[case.pk, item.pk]), HTTP_ACCEPT='application/json')
                self.assertEqual(response.json()['status'], 'success')

        # 19:40 UTC = 16:40 em Fortaleza: a janela no nfdump é no fuso dos logs.
        self.assertIn('2026/03/17.16:35:00-2026/03/17.16:45:00', ssh.commands[0])
        self.assertIn('João da Silva', response.json()['html'])

        first.refresh_from_db()
        self.assertEqual(first.data['sessions']['100.64.0.10'][0]['login'], 'joao')
        raw = raw_column(CaseItem, 'result', first.pk)
        self.assertNotIn('joao', raw)  # snapshot cifrado

        logs = SearchLog.objects.filter(case=case)
        self.assertEqual(logs.count(), 2)
        self.assertEqual(logs.first().query_timezone, 'UTC')

        response = self.client.post(reverse('cases:report', args=[case.pk]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

        report = CaseReport.objects.get()
        self.assertEqual(report.content_sha256, content_hash(case, list(case.items.all())))
        self.assertEqual(len(report.file_sha256), 64)
        self.assertIn(report.code, response['Content-Disposition'])

        detail = self.client.get(reverse('cases:detail', args=[case.pk]))
        self.assertContains(detail, report.content_sha256)
        self.assertContains(detail, 'Assinante identificado')

    def test_invalid_lines_are_reported_and_nothing_is_added(self):
        case = self.open_case()
        response = self.add(case, '203.0.113.1;17/03/2026 16:40:00\nlixo 1;2')
        self.assertContains(response, 'Linha 2')
        self.assertFalse(case.items.exists())

    def test_timezone_must_be_chosen(self):
        case = self.open_case()
        response = self.add(case, '203.0.113.1;17/03/2026 16:40:00', tz='')
        self.assertContains(response, 'has-error')
        self.assertFalse(case.items.exists())

    def test_no_logs_item(self):
        case = self.open_case()
        self.add(case, '203.0.113.1;2026-03-10 10:00:00')
        item = case.items.get()
        with mock.patch('apps.servers.services.flow_service.SSHClient', FakeSSH({})):
            self.client.post(reverse('cases:item_run', args=[case.pk, item.pk]))
        item.refresh_from_db()
        self.assertEqual(item.status, CaseItem.Status.NO_LOGS)
        self.assertIn('Sem logs', item.error_message)

    def test_answered_case_is_frozen(self):
        case = self.open_case()
        self.add(case, '203.0.113.1;2026-03-17 19:40:00')
        self.client.post(reverse('cases:status', args=[case.pk]), {'status': 'answered'})
        case.refresh_from_db()
        self.assertIsNotNone(case.answered_at)

        item = case.items.get()
        with mock.patch('apps.servers.services.flow_service.SSHClient') as ssh:
            self.client.post(reverse('cases:item_run', args=[case.pk, item.pk]))
            ssh.assert_not_called()
        self.add(case, '203.0.113.2;2026-03-17 19:40:00')
        self.assertEqual(case.items.count(), 1)

    def test_operator_sees_only_own_cases_admin_sees_all(self):
        case = self.open_case()
        other = make_member(self.org)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('cases:detail', args=[case.pk])).status_code, 404)

        admin = make_member(self.org, role='admin')
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('cases:detail', args=[case.pk])).status_code, 200)

    def test_other_organization_case_is_hidden(self):
        case = self.open_case()
        outsider = make_member(make_organization(), role='admin')
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse('cases:detail', args=[case.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('cases:report', args=[case.pk])).status_code, 404)

    def test_list_filters_by_status(self):
        self.open_case(number='OF-1')
        answered = self.open_case(number='OF-2')
        answered.status = Case.Status.ANSWERED
        answered.save()
        response = self.client.get(reverse('cases:list'))
        self.assertContains(response, 'OF-1')
        self.assertNotContains(response, 'OF-2')
        self.assertContains(self.client.get(reverse('cases:list'), {'status': 'answered'}), 'OF-2')
