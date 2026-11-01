import logging
import select
import socket
import threading

logger = logging.getLogger(__name__)

BUFFER_SIZE = 32 * 1024


class SSHTunnel:
    """Encaminha uma porta local (127.0.0.1) até host:port pelo SSH já conectado.

        with SSHClient(server) as ssh, SSHTunnel(ssh, "10.0.0.5", 3306) as port:
            pymysql.connect(host="127.0.0.1", port=port, ...)

    O canal é aberto antes de devolver a porta, então um destino inacessível
    falha aqui com uma mensagem clara, e não como "conexão perdida" no driver.
    Aceita uma única conexão: o suficiente para o driver do banco.
    """

    def __init__(self, ssh, host, port, accept_timeout=10):
        self.ssh = ssh
        self.host = host
        self.port = port
        self.accept_timeout = accept_timeout
        self.channel = None
        self.listener = None
        self.thread = None
        self._closed = threading.Event()

    def __enter__(self):
        self.channel = self.ssh.open_direct_channel(self.host, self.port)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(self.accept_timeout)
        self.thread = threading.Thread(target=self._serve, name="ssh-tunnel", daemon=True)
        self.thread.start()
        return self.listener.getsockname()[1]

    def __exit__(self, exc_type, exc, tb):
        self._closed.set()
        self.listener.close()
        self.channel.close()
        self.thread.join(timeout=2)

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        finally:
            self.listener.close()

        conn.setblocking(True)
        with conn:
            try:
                self._pump(conn)
            except OSError as e:
                if not self._closed.is_set():
                    logger.warning("Túnel SSH até %s:%s encerrado: %s", self.host, self.port, e)

    def _pump(self, conn):
        while not self._closed.is_set():
            readable, _, _ = select.select([conn, self.channel], [], [], 0.5)
            if conn in readable:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    return
                self.channel.sendall(data)
            if self.channel in readable:
                data = self.channel.recv(BUFFER_SIZE)
                if not data:
                    return
                conn.sendall(data)
