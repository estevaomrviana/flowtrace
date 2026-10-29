import csv
import logging
import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.generic import ListView, View

from .forms import FlowSearchForm
from .models import Server
from .services.exceptions import NoLogsFound, ServerConnectionError
from .services.flow_service import FlowService

logger = logging.getLogger(__name__)


class ServerList(LoginRequiredMixin, ListView):
    model = Server
    template_name = 'servers/server/list.html'


class FlowSearchView(LoginRequiredMixin, View):
    """Busca por GET: a URL da consulta pode ser compartilhada e exportada (?export=csv)."""

    template_name = "servers/server/search.html"

    def get(self, request, pk):
        server = get_object_or_404(Server, pk=pk)
        form = FlowSearchForm(request.GET or None)

        result = None
        error = None

        if form.is_bound and form.is_valid():
            result, error = self.run_search(server, form.to_query())

            if result and request.GET.get("export") == "csv":
                return self.export_csv(result)

        context = {
            "server": server,
            "form": form,
            "result": result,
            "error": error,
        }
        return render(request, self.template_name, context)

    def run_search(self, server, query):
        try:
            return FlowService(server).search(query), None

        except NoLogsFound as e:
            days = ", ".join(day.strftime("%d/%m/%Y") for day in e.days)
            return None, {
                "level": "info",
                "title": "Sem logs para o período",
                "text": f"O servidor não possui registros para {days}.",
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

    @staticmethod
    def export_csv(result):
        query = result.query
        filename = f"flowtrace_{query.ip}_{query.target:%Y%m%d_%H%M%S}.csv"

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("﻿")  # BOM para o Excel reconhecer UTF-8

        writer = csv.writer(response, delimiter=";")
        writer.writerow([
            "ip_publico", "porta_consultada", "horario_consultado",
            "correspondencia", "data_hora", "diferenca_segundos",
            "ip_origem", "bloco_inicio", "bloco_fim",
        ])
        for r in result.records:
            writer.writerow([
                query.ip,
                query.port or "",
                query.target.strftime("%d/%m/%Y %H:%M:%S"),
                "exato" if r.is_exact else "proximo",
                r.flow_time.strftime("%d/%m/%Y %H:%M:%S"),
                r.delta_seconds,
                r.source_ip,
                r.port_block_start if r.port_block_start is not None else "",
                r.port_block_end if r.port_block_end is not None else "",
            ])

        return response
