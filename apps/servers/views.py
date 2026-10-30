import csv
import logging
import uuid

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from apps.audit.models import SearchLog
from apps.audit.services import record_search
from apps.organizations.exceptions import QuotaExceeded
from apps.organizations.mixins import OrganizationMemberMixin, ServerManagerMixin

from .forms import FlowSearchForm, ServerForm
from .models import Server
from .services.exceptions import HostKeyMismatch, NoLogsFound, ServerConnectionError
from .services.flow_service import FlowService
from .services.health import check_server
from .services.registry import register_server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- Busca

class ServerList(OrganizationMemberMixin, ListView):
    template_name = 'servers/server/list.html'

    def get_queryset(self):
        return Server.objects.for_organization(self.organization).active()


class FlowSearchView(OrganizationMemberMixin, View):
    """Busca por GET: a URL da consulta pode ser compartilhada e exportada (?export=csv)."""

    template_name = "servers/server/search.html"

    def get(self, request, pk):
        server = get_object_or_404(
            Server.objects.for_organization(self.organization).active().select_related('credential'),
            pk=pk,
        )
        form = FlowSearchForm(request.GET or None)

        result = None
        error = None

        if form.is_bound and form.is_valid():
            query = form.to_query()
            exporting = request.GET.get("export") == "csv"
            result, error = self.run_search(server, query)

            record_search(
                request=request, membership=self.membership, server=server, query=query,
                action=SearchLog.Action.EXPORT if exporting else SearchLog.Action.SEARCH,
                status=self._status(result, error),
                result_count=len(result.records) if result else 0,
                error_id=(error or {}).get("id", ""),
            )

            if result and exporting:
                return self.export_csv(result)

        context = {
            "server": server,
            "form": form,
            "result": result,
            "error": error,
        }
        return render(request, self.template_name, context)

    @staticmethod
    def _status(result, error):
        if result is not None:
            return SearchLog.Status.SUCCESS
        if error and error["level"] == "info":
            return SearchLog.Status.NO_LOGS
        return SearchLog.Status.ERROR

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


# ---------------------------------------------------------------- Gestão

class ServerManageList(OrganizationMemberMixin, ListView):
    """Administradores veem todos os servidores; só editam os que a organização cadastrou."""

    template_name = 'servers/manage/list.html'
    context_object_name = 'servers'

    def has_organization_permission(self):
        return self.membership.is_admin

    def get_queryset(self):
        return Server.objects.for_organization(self.organization).select_related('credential')


class EditableServerMixin(ServerManagerMixin):
    """Restringe a servidores da organização que não são gerenciados pela plataforma."""

    def get_queryset(self):
        return Server.objects.for_organization(self.organization).filter(managed_by_platform=False)


class ServerCreateView(ServerManagerMixin, CreateView):
    template_name = 'servers/manage/form.html'
    form_class = ServerForm
    success_url = reverse_lazy('servers:manage')

    def get(self, request, *args, **kwargs):
        if not self.organization.has_server_quota():
            messages.warning(request, 'Sua organização atingiu o limite de servidores do plano.')
            return redirect(self.success_url)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            self.object = register_server(
                organization=self.organization, created_by=self.request.user, form=form,
            )
        except QuotaExceeded as e:
            messages.error(self.request, str(e))
            return redirect(self.success_url)

        messages.success(self.request, f'Servidor {self.object} cadastrado. Teste a conexão para validar o acesso.')
        return redirect(self.success_url)


class ServerUpdateView(EditableServerMixin, UpdateView):
    template_name = 'servers/manage/form.html'
    form_class = ServerForm
    success_url = reverse_lazy('servers:manage')

    def form_valid(self, form):
        messages.success(self.request, 'Servidor atualizado.')
        return super().form_valid(form)


class ServerDeleteView(EditableServerMixin, DeleteView):
    template_name = 'servers/manage/confirm_delete.html'
    success_url = reverse_lazy('servers:manage')

    def form_valid(self, form):
        messages.success(self.request, f'Servidor {self.object} removido.')
        return super().form_valid(form)


class ServerActionView(OrganizationMemberMixin, View):
    """Ações POST sobre um servidor da organização (somente administradores)."""

    http_method_names = ['post']

    def has_organization_permission(self):
        return self.membership.is_admin

    def get_server(self):
        return get_object_or_404(
            Server.objects.for_organization(self.organization).select_related('credential'),
            pk=self.kwargs['pk'],
        )


class ServerTestView(ServerActionView):
    def post(self, request, pk):
        server = self.get_server()
        report = check_server(server)
        level = messages.SUCCESS if report.ok else messages.ERROR
        messages.add_message(request, level, f'{server}: {report.message}')
        return redirect('servers:manage')


class ServerResetHostKeyView(ServerActionView):
    def post(self, request, pk):
        server = self.get_server()
        credential = getattr(server, 'credential', None)
        if credential is None or not server.is_editable_by(self.membership):
            raise Http404
        credential.reset_host_key()
        messages.success(request, f'Chave do host de {server} redefinida. A próxima conexão registrará a nova chave.')
        return redirect('servers:manage')
