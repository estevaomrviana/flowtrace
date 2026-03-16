from .ssh_client import SSHClient
from .nfdump_builder import NFDumpCommandBuilder
from .nfdump_parser import NFDumpParser


class FlowService:

    def __init__(self, server):
        self.server = server

    def search_flow(self, ip, target_datetime, port=None, minute_margin=5):

        ssh = SSHClient(self.server)

        ssh.connect()

        try:

            command = NFDumpCommandBuilder.build(
                ip,
                target_datetime,
                minute_margin
            )

            full_command = f"cd {self.server.log_path} && {command}"

            result = ssh.execute_command(full_command)

            flows = NFDumpParser.parse(
                result,
                target_datetime,
                port
            )

            return flows

        finally:

            ssh.close()

