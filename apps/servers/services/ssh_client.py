import logging
from dataclasses import dataclass

import paramiko
from django.conf import settings

from .exceptions import RemoteCommandError, ServerConnectionError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str


class SSHClient:
    """Wrapper mínimo sobre o paramiko, usado como context manager:

        with SSHClient(server) as ssh:
            result = ssh.run("comando")
    """

    def __init__(self, server, connect_timeout=None, command_timeout=None):
        self.server = server
        self.connect_timeout = connect_timeout or settings.SSH_CONNECT_TIMEOUT
        self.command_timeout = command_timeout or settings.SSH_COMMAND_TIMEOUT
        self.client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=self.server.host,
                port=self.server.port,
                username=self.server.username,
                password=self.server.password,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
            )
        except (paramiko.SSHException, OSError) as e:
            client.close()
            raise ServerConnectionError(
                f"Falha ao conectar em {self.server.host}:{self.server.port}: {e}"
            ) from e

        self.client = client

    def run(self, command):
        if self.client is None:
            raise ServerConnectionError("Cliente SSH não conectado")

        logger.debug("SSH %s: %s", self.server.host, command)

        try:
            _, stdout, stderr = self.client.exec_command(
                command, timeout=self.command_timeout
            )
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            status = stdout.channel.recv_exit_status()
        except (paramiko.SSHException, OSError) as e:
            raise RemoteCommandError(f"Falha ao executar comando remoto: {e}") from e

        return CommandResult(exit_status=status, stdout=out, stderr=err)

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None
