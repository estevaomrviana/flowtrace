import logging
import uuid

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView, View
from django.utils import timezone

from .models import Server
from .forms import FlowSearchForm
from .services.flow_service import FlowService

logger = logging.getLogger(__name__)


class ServerList(LoginRequiredMixin, ListView):
    model = Server
    template_name = 'servers/server/list.html'


class ServerDetailView(LoginRequiredMixin, DetailView):
    model = Server
    template_name = 'servers/server/detail.html'


class FlowSearchView(LoginRequiredMixin, View):
    template_name = "servers/server/search.html"

    def get(self, request, pk):
        server = get_object_or_404(Server, pk=pk)
        form = FlowSearchForm()

        context = {
            "server": server,
            "form": form,
            "results": [],
            "searched": False,
            "message": None,
        }

        return render(request, self.template_name, context)

    def post(self, request, pk):
        server = get_object_or_404(Server, pk=pk)
        form = FlowSearchForm(request.POST)

        results = []
        searched = True
        message = None

        if form.is_valid():
            ip = form.cleaned_data["ip"]
            datetime_target = timezone.make_naive(form.cleaned_data["datetime"])
            port = form.cleaned_data["port"]
            minute_margin = form.cleaned_data["minute_margin"]

            service = FlowService(server)

            try:
                results = service.search_flow(
                    ip=ip,
                    target_datetime=datetime_target,
                    port=port,
                    minute_margin=minute_margin
                ) or []

                if not results:
                    message = "Não encontramos logs para o dia consultado"

            except RuntimeError as e:
                error_id = uuid.uuid4()
                
                logger.exception(
                    f"[Erro ID {error_id}]: {str(e)}"
                )
                
                if "No such file or directory" in str(e):
                    message = "Não encontramos logs para o dia consultado"
                    
                else:
                    message = (
                        f"Ocorreu um erro inesperado (ID: {error_id}). "
                        "Por favor, entre em contato com o suporte."
                    )

            except Exception as e:
                error_id = uuid.uuid4()

                logger.exception(
                    f"[Erro ID {error_id}]: {str(e)}"
                )

                message = (
                    f"Ocorreu um erro inesperado (ID: {error_id}). "
                    "Por favor, entre em contato com o suporte."
                )

        context = {
            "server": server,
            "form": form,
            "results": results,
            "searched": searched,
            "message": message,
        }

        return render(request, self.template_name, context)
