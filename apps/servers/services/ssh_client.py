import paramiko


class SSHClient:

    def __init__(self, server):
        self.server = server
        self.client = None

    def connect(self):

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self.client.connect(
            hostname=self.server.host,
            port=self.server.port,
            username=self.server.username,
            password=self.server.password
        )

    def execute_command(self, command):

        if not self.client:
            raise RuntimeError("SSH client is not connected")

        stdin, stdout, stderr = self.client.exec_command(command)

        output = stdout.read().decode()
        error = stderr.read().decode()

        if error:
            raise RuntimeError(error)

        return output

    def close(self):

        if self.client:
            self.client.close()

