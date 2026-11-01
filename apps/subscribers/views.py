from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from apps.organizations.mixins import OrganizationAdminMixin, ServerManagerMixin

from .forms import SubscriberSourceForm
from .models import SubscriberSource
from .services import check_source


class SourceList(OrganizationAdminMixin, ListView):
    template_name = 'subscribers/source_list.html'
    context_object_name = 'sources'

    def get_queryset(self):
        return SubscriberSource.objects.for_organization(self.organization).select_related('ssh_server')


class SourceFormMixin(ServerManagerMixin):
    model = SubscriberSource
    form_class = SubscriberSourceForm
    template_name = 'subscribers/source_form.html'
    success_url = reverse_lazy('subscribers:list')

    def get_queryset(self):
        return SubscriberSource.objects.for_organization(self.organization).filter(managed_by_platform=False)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), 'organization': self.organization}


class SourceCreateView(SourceFormMixin, CreateView):

    def form_valid(self, form):
        self.object = form.save(organization=self.organization, created_by=self.request.user)
        messages.success(self.request, f'Fonte {self.object} cadastrada. Teste a conexão para validar o acesso.')
        return redirect(self.success_url)


class SourceUpdateView(SourceFormMixin, UpdateView):

    def form_valid(self, form):
        messages.success(self.request, 'Fonte atualizada.')
        return super().form_valid(form)


class SourceDeleteView(SourceFormMixin, DeleteView):
    template_name = 'subscribers/source_confirm_delete.html'

    def form_valid(self, form):
        messages.success(self.request, f'Fonte {self.object} removida.')
        return super().form_valid(form)


class SourceTestView(OrganizationAdminMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        source = get_object_or_404(
            SubscriberSource.objects.for_organization(self.organization).select_related('ssh_server__credential'),
            pk=pk,
        )
        report = check_source(source)
        level = messages.SUCCESS if report.ok else messages.ERROR
        messages.add_message(request, level, f'{source}: {report.message}')
        return redirect('subscribers:list')
