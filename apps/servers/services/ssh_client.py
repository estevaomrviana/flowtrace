import base64
import io
import logging
from dataclasses import dataclass

import paramiko
from django.conf import settings

from .exceptions import (
    CredentialMissing,
    HostKeyMismatch,
    RemoteCommandError,
    ServerConnectionError,
)

logger = logging.getLogger(__name__)

KEY_CLASSES = (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey)


@dataclass(frozen=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str


def load_private_key(text, passphrase=None):
    """Lê uma chave privada OpenSSH/PEM em memória. Levanta ValueError se inválida."""
    last_error = None
    for key_class in KEY_CLASSES:
        try:
            return key_class.from_private_key(io.StringIO(text), password=passphrase or None)
        except paramiko.PasswordRequiredException as e:
            raise ValueError("A chave está protegida por senha.") from e
        except (paramiko.SSHException, ValueError) as e:
            last_error = e
    raise ValueError(f"Chave privada inválida ou não suportada: {last_error}")


def format_host_key(key):
    return f"{key.get_name()} {key.get_base64()}"


def parse_host_key(text):
    key_type, b64 = text.split()[:2]
    return paramiko.PKey.from_type_string(key_type, base64.b64decode(b64))


class _CaptureHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Primeira conexão: aceita e memoriza a chave para fixá-la depois."""

    def __init__(self):
        self.key = None

    def missing_host_key(self, client, hostname, key):
        self.key = key


class SSHClient:
    """Wrapper mínimo sobre o paramiko, usado como context manager:

        with SSHClient(server) as ssh:
            result = ssh.run("comando")

    A chave do host é fixada na primeira conexão (ServerCredential.host_key);
    a partir daí uma chave diferente é recusada.
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

    def _credential(self):
        credential = getattr(self.server, "credential", None)
        if credential is None or not credential.has_secret:
            raise CredentialMissing(f"Servidor {self.server} sem credencial configurada")
        return credential

    def _auth_kwargs(self, credential):
        if credential.auth_method == credential.AuthMethod.KEY:
            try:
                pkey = load_private_key(
                    credential.private_key.reveal(), credential.key_passphrase.reveal(),
                )
            except ValueError as e:
                raise ServerConnectionError(str(e)) from e
            return {"pkey": pkey, "look_for_keys": False, "allow_agent": False}

        return {
            "password": credential.password.reveal(),
            "look_for_keys": False,
            "allow_agent": False,
        }

    def connect(self):
        credential = self._credential()
        server = self.server

        client = paramiko.SSHClient()
        capture = None

        if credential.host_key:
            entry = server.host if server.port == 22 else f"[{server.host}]:{server.port}"
            known = parse_host_key(credential.host_key)
            client.get_host_keys().add(entry, known.get_name(), known)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            capture = _CaptureHostKeyPolicy()
            client.set_missing_host_key_policy(capture)

        try:
            client.connect(
                hostname=server.host,
                port=server.port,
                username=credential.username,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
                **self._auth_kwargs(credential),
            )
        except paramiko.BadHostKeyException as e:
            client.close()
            raise HostKeyMismatch(
                f"A chave SSH de {server.host} mudou. Conexão recusada."
            ) from e
        except (paramiko.SSHException, OSError) as e:
            client.close()
            raise ServerConnectionError(
                f"Falha ao conectar em {server.host}:{server.port}: {e}"
            ) from e

        self.client = client

        if capture is not None and capture.key is not None:
            credential.remember_host_key(format_host_key(capture.key))
            logger.info("Chave do host registrada para %s", server)

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

    def open_direct_channel(self, host, port):
        """Canal TCP até host:port partindo do servidor SSH (base do SSHTunnel)."""
        if self.client is None:
            raise ServerConnectionError("Cliente SSH não conectado")

        try:
            return self.client.get_transport().open_channel(
                "direct-tcpip", (host, port), ("127.0.0.1", 0), timeout=self.connect_timeout,
            )
        except (paramiko.SSHException, OSError) as e:
            raise ServerConnectionError(
                f"{self.server.host} não conseguiu abrir conexão com {host}:{port}: {e}"
            ) from e

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None
