"""Onde os comandos do nfdump rodam: no servidor remoto (SSH) ou na própria máquina.

As duas classes têm a mesma interface (context manager + run(command)), então
FlowService, a verificação de saúde e a coleta não precisam saber a diferença.
"""
import logging
import subprocess

from django.conf import settings

from .exceptions import RemoteCommandError, ServerConnectionError
from .ssh_client import CommandResult, SSHClient

logger = logging.getLogger(__name__)


class LocalRunner:
    """Executa os comandos com /bin/sh na máquina do flowtrace (logs em FLOWTRACE_DATA_ROOT)."""

    shell = "/bin/sh"

    def __init__(self, server, command_timeout=None):
        self.server = server
        self.command_timeout = command_timeout or settings.SSH_COMMAND_TIMEOUT

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass

    def run(self, command):
        logger.debug("local %s: %s", self.server, command)
        try:
            proc = subprocess.run(
                [self.shell, "-c", command],
                capture_output=True, timeout=self.command_timeout, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RemoteCommandError(f"Comando local excedeu {self.command_timeout} s") from e
        except OSError as e:
            raise RemoteCommandError(f"Falha ao executar comando local: {e}") from e

        return CommandResult(
            exit_status=proc.returncode,
            stdout=proc.stdout.decode(errors="replace"),
            stderr=proc.stderr.decode(errors="replace"),
        )

    def open_direct_channel(self, host, port):
        raise ServerConnectionError("Servidor em execução local não abre túnel SSH.")


def runner_for(server, ssh_factory=SSHClient):
    """Executor adequado ao servidor. `ssh_factory` existe para os testes trocarem o SSH."""
    if server.is_local:
        return LocalRunner(server)
    return ssh_factory(server)
