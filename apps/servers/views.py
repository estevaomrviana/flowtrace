import csv

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from apps.audit.models import SearchLog
from apps.audit.services import record_search
from apps.organizations.exceptions import QuotaExceeded
from apps.organizations.mixins import OrganizationMemberMixin, ServerManagerMixin
from apps.subscribers.services import SubscriberLookup

from .forms import FlowSearchForm, ServerForm
from .models import Server
from .services.health import check_server
from .services.registry import register_server
from .services.search import run_search


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
        form = FlowSearchForm(request.GET or None, server=server)
        outcome = None

        if form.is_bound and form.is_valid():
            query = form.to_query()
            exporting = request.GET.get("export") == "csv"
            outcome = run_search(server, query, SubscriberLookup.for_organization(self.organization))

            record_search(
                request=request, membership=self.membership, server=server, query=query,
                action=SearchLog.Action.EXPORT if exporting else SearchLog.Action.SEARCH,
                status=outcome.status,
                result_count=outcome.result_count,
                error_id=outcome.error_id,
            )

            if outcome.result and exporting:
                return self.export_csv(outcome)

        context = {
            "server": server,
            "form": form,
            "result": outcome.result if outcome else None,
            "error": outcome.error if outcome else None,
            "rows": self.rows(outcome),
            "subscriber_errors": outcome.subscribers.errors if outcome and outcome.subscribers else [],
            "has_sources": outcome is not None and outcome.subscribers is not None,
        }
        return render(request, self.template_name, context)

    @staticmethod
    def rows(outcome):
        if outcome is None or outcome.result is None:
            return []
        return [(r, outcome.sessions_for(r.source_ip)) for r in outcome.result.records]

    @classmethod
    def export_csv(cls, outcome):
        query = outcome.result.query
        filename = f"flowtrace_{query.ip}_{query.target:%Y%m%d_%H%M%S}.csv"

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("﻿")  # BOM para o Excel reconhecer UTF-8

        writer = csv.writer(response, delimiter=";")
        writer.writerow([
            "ip_publico", "porta_consultada", "horario_informado", "fuso_informado",
            "horario_consultado", "fuso_logs",
            "correspondencia", "data_hora", "diferenca_segundos",
            "ip_origem", "bloco_inicio", "bloco_fim",
            "assinante_login", "assinante_mac", "sessao_inicio", "sessao_fim", "cadastro",
        ])
        for r, sessions in cls.rows(outcome):
            base = [
                query.ip,
                query.port or "",
                query.informed.strftime("%d/%m/%Y %H:%M:%S"),
                query.input_tz,
                query.target.strftime("%d/%m/%Y %H:%M:%S"),
                query.log_tz,
                "exato" if r.is_exact else "proximo",
                r.flow_time.strftime("%d/%m/%Y %H:%M:%S"),
                r.delta_seconds,
                r.source_ip,
                r.port_block_start if r.port_block_start is not None else "",
                r.port_block_end if r.port_block_end is not None else "",
            ]
            for s in sessions or [None]:
                writer.writerow(base + ([
                    s.login,
                    s.mac,
                    s.started_at.strftime("%d/%m/%Y %H:%M:%S") if s.started_at else "",
                    s.stopped_at.strftime("%d/%m/%Y %H:%M:%S") if s.stopped_at else "em aberto",
                    " | ".join(f"{k}: {v}" for k, v in s.customer.items()),
                ] if s else ["", "", "", "", ""]))

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
