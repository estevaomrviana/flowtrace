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
            # print(f"\n[2] Comando completo: {full_command}")
            
            result = ssh.execute_command(full_command)

            # print("Retorno: ", result)

            flows = NFDumpParser.parse(
                result,
                target_datetime,
                port
            )

            # print(f"Quantidade de flows encontrados: {len(flows)}")
            
            return flows

        finally:
            ssh.close()
