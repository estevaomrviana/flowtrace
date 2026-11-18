from django.core.management.base import BaseCommand

from apps.core.alerts import ping_healthcheck
from apps.servers.models import Server
from apps.servers.services.collection import sync_server


class Command(BaseCommand):
    help = (
        "Verifica a chegada de arquivos do nfcapd em cada servidor ativo, registra o SHA-256 "
        "dos arquivos novos no manifesto e alerta quando a coleta para. Agende a cada 5 minutos."
    )

    def add_arguments(self, parser):
        parser.add_argument("--server", type=int, action="append", help="ID do servidor (pode repetir).")
        parser.add_argument(
            "--days", type=int, default=2,
            help="Quantos dias para trás listar (padrão 2). Use mais para registrar arquivos antigos no manifesto.",
        )
        parser.add_argument("--no-alert", action="store_true", help="Não envia alertas.")

    def handle(self, *args, server=None, days=2, no_alert=False, **options):
        servers = Server.objects.active().select_related("organization", "credential")
        if server:
            servers = servers.filter(pk__in=server)

        problems = 0
        for srv in servers:
            report = sync_server(srv, days=days, alert=not no_alert)
            line = f"{srv.organization} / {srv}: {report.state} - {report.message}"
            if report.registered or report.pending:
                line += f" ({report.registered} arquivo(s) no manifesto, {report.pending} pendente(s))"
            if report.state != "ok":
                problems += 1
                self.stderr.write(line)
            else:
                self.stdout.write(line)

        ping_healthcheck(ok=True, details={"servers": servers.count(), "problems": problems})
