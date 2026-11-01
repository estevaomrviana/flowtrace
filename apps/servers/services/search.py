"""Busca completa usada pelas telas: fluxos no servidor de logs + assinante no RADIUS."""
import logging
import uuid
from dataclasses import dataclass

from apps.audit.models import SearchLog

from .exceptions import HostKeyMismatch, NoLogsFound, ServerConnectionError
from .flow_service import FlowService

logger = logging.getLogger(__name__)

# Com margem grande e sem porta, um IP público pode ter dezenas de IPs privados
# na janela; correlaciona os mais próximos do horário (a lista já vem ordenada).
MAX_CORRELATED_IPS = 20


@dataclass
class SearchOutcome:
    result: object = None  # FlowSearchResult
    error: dict | None = None
    subscribers: object = None  # LookupResult; None quando não há fonte configurada

    @property
    def status(self):
        if self.result is not None:
            return SearchLog.Status.SUCCESS
        if self.error and self.error["level"] == "info":
            return SearchLog.Status.NO_LOGS
        return SearchLog.Status.ERROR

    @property
    def result_count(self):
        return len(self.result.records) if self.result else 0

    @property
    def error_id(self):
        return (self.error or {}).get("id", "")

    def sessions_for(self, ip):
        return self.subscribers.for_ip(ip) if self.subscribers else []


def run_search(server, query, lookup=None):
    """Executa a busca sem levantar exceções: erros viram mensagens para a tela.

    `lookup` é um SubscriberLookup; quando informado (e com fontes), identifica
    o assinante de cada IP privado encontrado.
    """
    outcome = SearchOutcome()
    outcome.result, outcome.error = _search_flows(server, query)

    if outcome.result is not None and outcome.result.records and lookup:
        ips = list(dict.fromkeys(r.source_ip for r in outcome.result.records))[:MAX_CORRELATED_IPS]
        outcome.subscribers = lookup.find(ips, query.target, query.log_tz)

    return outcome


def _search_flows(server, query):
    try:
        return FlowService(server).search(query), None

    except NoLogsFound as e:
        days = ", ".join(day.strftime("%d/%m/%Y") for day in e.days)
        return None, {
            "level": "info",
            "title": "Sem logs para o período",
            "text": f"O servidor não possui registros para {days}.",
        }

    except HostKeyMismatch:
        error_id = uuid.uuid4().hex[:8]
        logger.error("[Erro %s] Chave do host mudou: %s", error_id, server)
        return None, {
            "level": "danger",
            "title": "Identidade do servidor alterada",
            "text": "A chave SSH do servidor mudou desde o cadastro e a conexão foi recusada "
                    "por segurança. Contate o administrador.",
            "id": error_id,
        }

    except ServerConnectionError:
        error_id = uuid.uuid4().hex[:8]
        logger.exception("[Erro %s] Conexão com %s", error_id, server)
        return None, {
            "level": "danger",
            "title": "Servidor indisponível",
            "text": "Não foi possível conectar ao servidor de logs. "
                    "Tente novamente em instantes.",
            "id": error_id,
        }

    except Exception:
        error_id = uuid.uuid4().hex[:8]
        logger.exception("[Erro %s] Busca em %s: %s", error_id, server, query)
        return None, {
            "level": "danger",
            "title": "Erro inesperado",
            "text": "A consulta não pôde ser concluída. "
                    "Informe o código ao suporte.",
            "id": error_id,
        }
