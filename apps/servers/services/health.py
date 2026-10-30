from dataclasses import dataclass

from .exceptions import FlowSearchError, HostKeyMismatch
from .nfdump_builder import quote_path
from .ssh_client import SSHClient

NFDUMP_MISSING_EXIT = 10
LOG_PATH_MISSING_EXIT = 11


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    message: str


def check_server(server, ssh_factory=None):
    """Conecta, confirma o nfdump instalado e a pasta de logs existente."""
    ssh_factory = ssh_factory or SSHClient
    command = (
        f"command -v nfdump >/dev/null 2>&1 || exit {NFDUMP_MISSING_EXIT}; "
        f"test -d {quote_path(server.log_path)} || exit {LOG_PATH_MISSING_EXIT}"
    )

    try:
        with ssh_factory(server) as ssh:
            result = ssh.run(command)
    except HostKeyMismatch:
        return HealthReport(False, "A chave SSH do servidor mudou. Se a troca foi legítima, redefina a chave do host.")
    except FlowSearchError as e:
        return HealthReport(False, str(e))

    if result.exit_status == NFDUMP_MISSING_EXIT:
        return HealthReport(False, "Conectado, mas o nfdump não foi encontrado no servidor.")
    if result.exit_status == LOG_PATH_MISSING_EXIT:
        return HealthReport(False, f"Conectado, mas a pasta {server.log_path} não existe.")
    if result.exit_status != 0:
        return HealthReport(False, f"Comando de verificação falhou (código {result.exit_status}).")

    return HealthReport(True, "Conexão OK: nfdump encontrado e pasta de logs acessível.")
