import json
from datetime import date, datetime

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from unittest import mock

from apps.audit.models import SearchLog
from apps.core.testing import make_member, make_organization, make_server

from .models import Server
from .services.exceptions import NFDumpOutputError, NoLogsFound, RemoteCommandError
from .services.flow_service import FlowQuery, FlowService
from .services.nfdump_builder import NFDumpCommandBuilder, TimeWindow, quote_path
from .services.nfdump_parser import NFDumpParser
from .services.ssh_client import CommandResult
from .templatetags.flowtrace import signed_delta

TARGET = datetime(2026, 3, 17, 16, 40, 0)


def flow(t_first, src="100.64.0.10", start=1024, end=1535, **extra):
    return {"t_first": t_first, "src4_addr": src, "pblock_start": start, "pblock_end": end, **extra}


class FakeSSH:
    """Substitui o SSHClient: responde pela pasta do dia (AAAA/MM/DD) passada em -R."""

    def __init__(self, responses):
        self.responses = responses
        self.commands = []

    def __call__(self, server):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def run(self, command):
        self.commands.append(command)
        folder = command.split(" -R ", 1)[1].split()[0]
        for day, result in self.responses.items():
            if day in folder:
                return result
        return CommandResult(3, "", "")


class TimeWindowTests(SimpleTestCase):

    def test_window_within_one_day(self):
        window = TimeWindow.around(TARGET, 5)
        self.assertEqual(list(window.days()), [date(2026, 3, 17)])
        self.assertEqual(window.as_nfdump_range(), "2026/03/17.16:35:00-2026/03/17.16:45:00")

    def test_window_crossing_midnight_covers_two_days(self):
        window = TimeWindow.around(datetime(2026, 3, 17, 23, 58), 5)
        self.assertEqual(list(window.days()), [date(2026, 3, 17), date(2026, 3, 18)])


class CommandBuilderTests(SimpleTestCase):

    def test_build_quotes_everything(self):
        window = TimeWindow.around(TARGET, 5)
        cmd = NFDumpCommandBuilder.build("/var/log/nf; rm -rf /", date(2026, 3, 17), window, "203.0.113.1")
        self.assertIn("'/var/log/nf; rm -rf /2026/03/17'", cmd)
        self.assertIn("'xip 203.0.113.1'", cmd)
        self.assertTrue(cmd.startswith("test -d "))

    def test_quote_path_keeps_home_expansion(self):
        self.assertEqual(quote_path("~/logs/2026"), '"$HOME"/logs/2026')
        self.assertEqual(quote_path("/data"), "/data")


class ParserTests(SimpleTestCase):

    def test_empty_output(self):
        self.assertEqual(NFDumpParser.parse("", TARGET), [])
        self.assertEqual(NFDumpParser.parse("  \n", TARGET), [])

    def test_exact_and_near(self):
        text = json.dumps([flow("2026-03-17T16:40:30.120"), flow("2026-03-17T16:43:00")])
        exact, near = NFDumpParser.parse(text, TARGET)
        self.assertTrue(exact.is_exact)
        self.assertEqual(exact.delta_seconds, 30)
        self.assertEqual(exact.flow_time, datetime(2026, 3, 17, 16, 40, 30))
        self.assertFalse(near.is_exact)

    def test_port_filter_uses_block_range(self):
        text = json.dumps([flow("2026-03-17T16:40:00", start=1024, end=1535),
                           flow("2026-03-17T16:40:00", start=2048, end=2559)])
        records = NFDumpParser.parse(text, TARGET, port=2100)
        self.assertEqual([r.port_block_start for r in records], [2048])

    def test_port_filter_without_block_does_not_crash(self):
        text = json.dumps([{"t_first": "2026-03-17T16:40:00", "src4_addr": "100.64.0.1"},
                           {"t_first": "2026-03-17T16:40:00", "src4_addr": "100.64.0.2", "xsrc_port": 5000}])
        records = NFDumpParser.parse(text, TARGET, port=5000)
        self.assertEqual([r.source_ip for r in records], ["100.64.0.2"])

    def test_skips_incomplete_records(self):
        text = json.dumps([{"src4_addr": "1.1.1.1"}, {"t_first": "lixo", "src4_addr": "1.1.1.1"}])
        self.assertEqual(NFDumpParser.parse(text, TARGET), [])

    def test_accepts_json_lines(self):
        text = "\n".join(json.dumps(flow("2026-03-17T16:40:00", src=f"100.64.0.{i}")) for i in range(3))
        self.assertEqual(len(NFDumpParser.parse(text, TARGET)), 3)

    def test_invalid_output_raises(self):
        with self.assertRaises(NFDumpOutputError):
            NFDumpParser.parse("Error: something", TARGET)


class FlowServiceTests(SimpleTestCase):

    def setUp(self):
        self.server = Server(name="cgnat", host="10.0.0.1", log_path="/logs")

    def test_searches_both_days_near_midnight_sorted_and_deduped(self):
        ssh = FakeSSH({
            "2026/03/17": CommandResult(0, json.dumps([
                flow("2026-03-17T23:56:00", src="100.64.0.1"),
                flow("2026-03-17T23:56:00", src="100.64.0.1"),
            ]), ""),
            "2026/03/18": CommandResult(0, json.dumps([flow("2026-03-18T00:00:10", src="100.64.0.2")]), ""),
        })
        query = FlowQuery(ip="203.0.113.1", target=datetime(2026, 3, 18, 0, 0, 0), minute_margin=5)

        result = FlowService(self.server, ssh_factory=ssh).search(query)

        self.assertEqual(len(ssh.commands), 2)
        self.assertEqual([r.source_ip for r in result.records], ["100.64.0.2", "100.64.0.1"])
        self.assertEqual(result.exact_count, 1)
        self.assertEqual(result.days_missing, [])

    def test_partial_missing_day(self):
        ssh = FakeSSH({"2026/03/17": CommandResult(0, "[]", "")})
        query = FlowQuery(ip="203.0.113.1", target=datetime(2026, 3, 17, 23, 58))

        result = FlowService(self.server, ssh_factory=ssh).search(query)

        self.assertEqual(result.days_missing, [date(2026, 3, 18)])
        self.assertEqual(result.records, [])

    def test_no_logs_at_all(self):
        with self.assertRaises(NoLogsFound):
            FlowService(self.server, ssh_factory=FakeSSH({})).search(FlowQuery("203.0.113.1", TARGET))

    def test_nfdump_failure(self):
        ssh = FakeSSH({"2026/03/17": CommandResult(255, "", "nfdump: bad filter")})
        with self.assertRaises(RemoteCommandError):
            FlowService(self.server, ssh_factory=ssh).search(FlowQuery("203.0.113.1", TARGET))

    def test_stderr_warning_with_success_is_not_an_error(self):
        ssh = FakeSSH({"2026/03/17": CommandResult(0, json.dumps([flow("2026-03-17T16:40:00")]), "warning")})
        result = FlowService(self.server, ssh_factory=ssh).search(FlowQuery("203.0.113.1", TARGET))
        self.assertEqual(len(result.records), 1)


class SignedDeltaTests(SimpleTestCase):

    def test_format(self):
        self.assertEqual(signed_delta(0), "0s")
        self.assertEqual(signed_delta(42), "+42s")
        self.assertEqual(signed_delta(-75), "−1m 15s")
        self.assertEqual(signed_delta(3700), "+1h 01m")


class SearchViewTests(TestCase):

    def setUp(self):
        self.org = make_organization()
        self.user = make_member(self.org)
        self.server = make_server(self.org)
        self.url = reverse("servers:search", args=[self.server.pk])
        self.params = {"ip": "203.0.113.1", "datetime": "2026-03-17T16:40:00", "minute_margin": "5"}

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_login_page_renders(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_empty_form(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["result"])

    def test_server_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("servers:list"))
        self.assertContains(response, "cgnat")

    def _fake(self, responses):
        ssh = FakeSSH(responses)
        return mock.patch("apps.servers.services.flow_service.SSHClient", ssh)

    def test_search_results_and_csv(self):
        self.client.force_login(self.user)
        stdout = json.dumps([flow("2026-03-17T16:40:05")])

        with self._fake({"2026/03/17": CommandResult(0, stdout, "")}):
            response = self.client.get(self.url, self.params)
        self.assertContains(response, "100.64.0.10")
        self.assertContains(response, "Exato")

        log = SearchLog.objects.get()
        self.assertEqual((log.organization, log.user, log.result_count), (self.org, self.user, 1))
        self.assertEqual(log.status, SearchLog.Status.SUCCESS)

        with self._fake({"2026/03/17": CommandResult(0, stdout, "")}):
            response = self.client.get(self.url, {**self.params, "export": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("100.64.0.10", response.content.decode("utf-8-sig"))
        self.assertEqual(SearchLog.objects.filter(action=SearchLog.Action.EXPORT).count(), 1)

    def test_no_logs_message(self):
        self.client.force_login(self.user)
        with self._fake({}):
            response = self.client.get(self.url, self.params)
        self.assertContains(response, "Sem logs para o período")
        self.assertEqual(SearchLog.objects.get().status, SearchLog.Status.NO_LOGS)

    def test_invalid_ip(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url, {**self.params, "ip": "999.1.1.1"})
        self.assertContains(response, "has-error")

    def test_cannot_search_other_organization_server(self):
        other = make_server(make_organization())
        self.client.force_login(self.user)
        response = self.client.get(reverse("servers:search", args=[other.pk]), self.params)
        self.assertEqual(response.status_code, 404)

    def test_inactive_server_is_hidden(self):
        self.server.is_active = False
        self.server.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_user_without_organization(self):
        from django.contrib.auth import get_user_model
        loner = get_user_model().objects.create_user("loner", password="x")
        self.client.force_login(loner)
        response = self.client.get(reverse("servers:list"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "não está vinculada", status_code=403)

    def test_inactive_organization_blocks_access(self):
        self.org.is_active = False
        self.org.save()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class TimezoneQueryTests(SimpleTestCase):

    def test_from_input_converts_to_log_timezone(self):
        server = Server(name="cgnat", timezone="America/Fortaleza")
        query = FlowQuery.from_input(
            ip="203.0.113.1", informed=datetime(2026, 3, 17, 19, 40), input_tz="UTC", server=server,
        )
        self.assertEqual(query.target, datetime(2026, 3, 17, 16, 40))
        self.assertEqual(query.informed, datetime(2026, 3, 17, 19, 40))
        self.assertTrue(query.converted)
        self.assertEqual(query.aware_target.utcoffset().total_seconds(), -3 * 3600)

    def test_same_offset_is_not_a_conversion(self):
        server = Server(name="cgnat", timezone="America/Fortaleza")
        query = FlowQuery.from_input(
            ip="203.0.113.1", informed=TARGET, input_tz="America/Sao_Paulo", server=server,
        )
        self.assertFalse(query.converted)

    def test_offset_label(self):
        from apps.core.timezones import utc_offset_label
        self.assertEqual(utc_offset_label(TARGET, "America/Fortaleza"), "UTC−03:00")
        self.assertEqual(utc_offset_label(TARGET, "UTC"), "UTC+00:00")


class SearchTimezoneAndSubscriberTests(TestCase):

    def setUp(self):
        self.org = make_organization()
        self.user = make_member(self.org)
        self.server = make_server(self.org, timezone="America/Fortaleza")
        self.url = reverse("servers:search", args=[self.server.pk])
        self.client.force_login(self.user)

    def test_utc_input_searches_converted_window(self):
        ssh = FakeSSH({"2026/03/17": CommandResult(0, json.dumps([flow("2026-03-17T16:40:05")]), "")})
        with mock.patch("apps.servers.services.flow_service.SSHClient", ssh):
            response = self.client.get(self.url, {
                "ip": "203.0.113.1", "datetime": "2026-03-17T19:40:00", "timezone": "UTC", "minute_margin": "5",
            })
        self.assertIn("2026/03/17.16:35:00-2026/03/17.16:45:00", ssh.commands[0])
        self.assertContains(response, "no fuso dos logs")
        self.assertEqual(SearchLog.objects.get().query_timezone, "UTC")

    def test_missing_timezone_uses_server_timezone(self):
        ssh = FakeSSH({"2026/03/17": CommandResult(0, "[]", "")})
        with mock.patch("apps.servers.services.flow_service.SSHClient", ssh):
            response = self.client.get(self.url, {"ip": "203.0.113.1", "datetime": "2026-03-17T16:40:00", "minute_margin": "5"})
        self.assertIn("2026/03/17.16:35:00-2026/03/17.16:45:00", ssh.commands[0])
        self.assertContains(response, '<option value="America/Fortaleza" selected>')

    def test_subscriber_column_and_csv(self):
        from apps.subscribers.services import SubscriberLookup
        from apps.subscribers.tests import FakeDB, make_source, session_row

        lookup = SubscriberLookup([make_source()], connector=FakeDB([session_row(login="joao.pppoe")]).connector)
        ssh = FakeSSH({"2026/03/17": CommandResult(0, json.dumps([flow("2026-03-17T16:40:05")]), "")})
        params = {"ip": "203.0.113.1", "datetime": "2026-03-17T16:40:00", "minute_margin": "5"}

        with mock.patch("apps.servers.services.flow_service.SSHClient", ssh), \
                mock.patch("apps.servers.views.SubscriberLookup.for_organization", return_value=lookup):
            response = self.client.get(self.url, params)
            self.assertContains(response, "joao.pppoe")
            csv_response = self.client.get(self.url, {**params, "export": "csv"})
        self.assertIn("joao.pppoe", csv_response.content.decode("utf-8-sig"))
