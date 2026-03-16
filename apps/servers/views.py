from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, FormView
from django.utils import timezone
from .models import Server
from .forms import FlowSearchForm
from .services.flow_service import FlowService



class IndexView(LoginRequiredMixin, ListView):
    model = Server
    template_name = 'servers/index.html'


class ServerDetailView(LoginRequiredMixin, DetailView):
    model = Server
    template_name = 'servers/detail.html'


class FlowSearchView(FormView):

    template_name = "servers/search.html"
    form_class = FlowSearchForm

    def form_valid(self, form):

        ip = form.cleaned_data["ip"]
        datetime_target = timezone.make_naive(form.cleaned_data["datetime"])
        port = form.cleaned_data["port"]
        minute_margin = form.cleaned_data["minute_margin"]

        server = Server.objects.first()

        service = FlowService(server)

        results = service.search_flow(
            ip=ip,
            target_datetime=datetime_target,
            port=port,
            minute_margin=minute_margin
        )

        context = self.get_context_data(
            form=form,
            results=results
        )

        return self.render_to_response(context)

