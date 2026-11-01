import hashlib

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.organizations.mixins import OrganizationMemberMixin

from .forms import BatchForm, CaseForm
from .models import Case, CaseReport
from .report import build_report
from .services import add_items, content_hash, item_result, run_item


class CaseQuerysetMixin(OrganizationMemberMixin):

    def get_queryset(self):
        return Case.objects.visible_to(self.membership)

    def get_case(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)


class CaseListView(CaseQuerysetMixin, ListView):
    template_name = 'cases/case_list.html'
    context_object_name = 'cases'
    paginate_by = 30

    def get_queryset(self):
        qs = super().get_queryset().select_related('created_by')
        status = self.request.GET.get('status', Case.Status.OPEN)
        if status in Case.Status.values:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        status = self.request.GET.get('status', Case.Status.OPEN)
        return super().get_context_data(
            status_filter=status,
            status_choices=Case.Status.choices,
            querystring=urlencode({'status': status}),
            **kwargs,
        )


class CaseCreateView(OrganizationMemberMixin, CreateView):
    template_name = 'cases/case_form.html'
    form_class = CaseForm

    def form_valid(self, form):
        form.instance.organization = self.organization
        form.instance.created_by = self.request.user
        self.object = form.save()
        messages.success(self.request, 'Requisição aberta. Inclua as consultas do ofício.')
        return redirect('cases:detail', self.object.pk)


class CaseUpdateView(CaseQuerysetMixin, UpdateView):
    template_name = 'cases/case_form.html'
    form_class = CaseForm

    def get_success_url(self):
        return reverse('cases:detail', args=[self.object.pk])


class CaseDetailView(CaseQuerysetMixin, DetailView):
    """Requisição com suas consultas; o POST inclui um lote de consultas."""

    template_name = 'cases/case_detail.html'
    context_object_name = 'case'

    def get_context_data(self, batch_form=None, **kwargs):
        case = self.object
        items = list(case.items.select_related('executed_by'))
        return super().get_context_data(
            items=[(item, item_result(item)) for item in items],
            pending_count=sum(1 for item in items if item.is_pending),
            batch_form=batch_form or BatchForm(organization=self.organization),
            reports=case.reports.select_related('generated_by'),
            **kwargs,
        )

    def post(self, request, pk):
        self.object = case = self.get_object()
        if not case.is_editable:
            messages.error(request, 'Reabra a requisição para incluir consultas.')
            return redirect('cases:detail', case.pk)

        form = BatchForm(request.POST, organization=self.organization)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(batch_form=form))

        created = len(add_items(
            case, form.parsed,
            server=form.cleaned_data['server'], minute_margin=form.cleaned_data['minute_margin'],
        ))
        plural = 's' if created != 1 else ''
        messages.success(request, f'{created} consulta{plural} incluída{plural}. Execute para obter os resultados.')
        return redirect('cases:detail', case.pk)


class CaseItemMixin(CaseQuerysetMixin):
    http_method_names = ['post']

    def get_item(self, pk, item_pk):
        case = self.get_case(pk)
        return get_object_or_404(case.items.select_related('case__organization'), pk=item_pk)

    def wants_json(self):
        return self.request.headers.get('Accept', '').startswith('application/json')


class CaseItemRunView(CaseItemMixin, View):

    def post(self, request, pk, item_pk):
        item = self.get_item(pk, item_pk)
        if item.case.is_editable:
            run_item(item, request=request, membership=self.membership)

        if self.wants_json():
            html = render_to_string(
                'cases/includes/item.html',
                {'item': item, 'result': item_result(item), 'case': item.case},
                request=request,
            )
            return JsonResponse({'status': item.status, 'html': html})

        if not item.case.is_editable:
            messages.error(request, 'Reabra a requisição para executar consultas.')
        return redirect(f"{reverse('cases:detail', args=[pk])}#item-{item.pk}")


class CaseItemDeleteView(CaseItemMixin, View):

    def post(self, request, pk, item_pk):
        item = self.get_item(pk, item_pk)
        if item.case.is_editable:
            item.delete()
            messages.success(request, 'Consulta removida.')
        return redirect('cases:detail', pk)


class CaseStatusView(CaseQuerysetMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        case = self.get_case(pk)
        status = request.POST.get('status')
        if status not in Case.Status.values:
            return redirect('cases:detail', pk)

        case.status = status
        case.answered_at = timezone.now() if status == Case.Status.ANSWERED else case.answered_at
        case.save(update_fields=['status', 'answered_at', 'updated_at'])
        messages.success(request, f'Requisição marcada como {case.get_status_display().lower()}.')
        return redirect('cases:detail', pk)


class CaseReportView(CaseQuerysetMixin, View):
    """Emite o PDF de resposta a partir dos resultados salvos (não consulta de novo)."""

    http_method_names = ['post']

    def post(self, request, pk):
        case = self.get_case(pk)
        items = list(case.items.all())

        if not items:
            messages.error(request, 'Inclua e execute as consultas antes de emitir a resposta.')
            return redirect('cases:detail', pk)
        if any(item.is_pending for item in items):
            messages.error(request, 'Há consultas pendentes. Execute todas antes de emitir a resposta.')
            return redirect('cases:detail', pk)

        digest = content_hash(case, items)
        with transaction.atomic():
            report = CaseReport.objects.create(
                case=case, generated_by=request.user, username=request.user.get_username(),
                content_sha256=digest, file_sha256='', item_count=len(items),
            )
            pdf = build_report(case, items, report, digest, request.user)
            report.file_sha256 = hashlib.sha256(pdf).hexdigest()
            report.save(update_fields=['file_sha256'])

        filename = f'resposta_{report.code}.pdf'
        response = HttpResponse(pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
