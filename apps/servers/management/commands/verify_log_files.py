from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.alerts import send_alert
from apps.servers.models import Server
from apps.servers.services.collection import verify_day


class Command(BaseCommand):
    help = (
        "Recalcula o SHA-256 dos arquivos de um dia e compara com o manifesto. "
        "Sem --day, confere um dia aleatório dos últimos 13 meses (teste mensal de integridade/restauração)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--server", type=int, action="append", help="ID do servidor (pode repetir).")
        parser.add_argument("--day", type=date.fromisoformat, help="Dia no formato AAAA-MM-DD.")
        parser.add_argument("--alert", action="store_true", help="Envia alerta se encontrar divergência.")

    def handle(self, *args, server=None, day=None, alert=False, **options):
        servers = Server.objects.active().select_related("organization", "credential")
        if server:
            servers = servers.filter(pk__in=server)

        failures = 0
        for srv in servers:
            target = day or self._random_day(srv)
            if target is None:
                self.stdout.write(f"{srv}: manifesto vazio, nada a conferir.")
                continue

            report = verify_day(srv, target)
            summary = (
                f"{srv.organization} / {srv} em {target:%d/%m/%Y}: {report.checked} arquivo(s) conferido(s), "
                f"{len(report.mismatched)} divergente(s), {len(report.missing)} ausente(s)"
            )
            if report.ok:
                self.stdout.write(summary)
                continue

            failures += 1
            self.stderr.write(summary)
            for path in report.mismatched:
                self.stderr.write(f"  hash diferente: {path}")
            for path in report.missing:
                self.stderr.write(f"  não encontrado: {path}")
            if alert:
                send_alert(f"[FlowTrace] Conferência de integridade falhou. {summary}")

        if failures:
            raise CommandError(f"{failures} servidor(es) com divergência no manifesto.")

    @staticmethod
    def _random_day(server):
        """Dia de um arquivo sorteado do manifesto (dentro dos 13 meses de retenção)."""
        since = timezone.now() - timedelta(days=395)
        sample = (
            server.log_files.filter(interval_start__gte=since)
            .order_by("?").values_list("path", flat=True).first()
        )
        return date(*map(int, sample.split("/")[:3])) if sample else None
