class FlowSearchError(Exception):
    """Erro base da busca de fluxos."""


class ServerConnectionError(FlowSearchError):
    """Não foi possível conectar ou autenticar no servidor via SSH."""


class RemoteCommandError(FlowSearchError):
    """O comando remoto falhou (timeout, código de saída diferente de zero)."""


class NFDumpOutputError(FlowSearchError):
    """A saída do nfdump não pôde ser interpretada."""


class NoLogsFound(FlowSearchError):
    """Não existe pasta de logs para nenhum dos dias da janela consultada."""

    def __init__(self, days):
        self.days = list(days)
        super().__init__(
            "Sem pasta de logs para: "
            + ", ".join(day.strftime("%d/%m/%Y") for day in self.days)
        )
