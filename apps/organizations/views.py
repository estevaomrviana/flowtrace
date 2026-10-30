from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView, TemplateView

from .exceptions import QuotaExceeded
from .forms import MemberCreateForm, MemberUpdateForm
from .mixins import OrganizationAdminMixin
from .services import add_member, update_member


class OrganizationDetailView(OrganizationAdminMixin, TemplateView):
    template_name = 'organizations/detail.html'

    def get_context_data(self, **kwargs):
        org = self.organization
        return super().get_context_data(
            server_count=org.server_count,
            member_count=org.member_count,
            **kwargs,
        )


class MemberListView(OrganizationAdminMixin, ListView):
    template_name = 'organizations/member_list.html'
    context_object_name = 'memberships'

    def get_queryset(self):
        return self.organization.memberships.select_related('user')


class MemberCreateView(OrganizationAdminMixin, FormView):
    template_name = 'organizations/member_form.html'
    form_class = MemberCreateForm
    success_url = reverse_lazy('organizations:members')

    def get(self, request, *args, **kwargs):
        if not self.organization.has_member_quota():
            messages.warning(request, 'Sua organização atingiu o limite de usuários do plano.')
            return redirect(self.success_url)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            membership = add_member(organization=self.organization, form=form)
        except QuotaExceeded as e:
            messages.error(self.request, str(e))
            return redirect(self.success_url)

        messages.success(self.request, f'Usuário {membership.user.username} criado.')
        return super().form_valid(form)


class MemberUpdateView(OrganizationAdminMixin, FormView):
    template_name = 'organizations/member_form.html'
    success_url = reverse_lazy('organizations:members')

    def get_membership(self):
        if not hasattr(self, '_target'):
            self._target = get_object_or_404(
                self.organization.memberships.select_related('user'), pk=self.kwargs['pk'],
            )
        return self._target

    def get_form(self, form_class=None):
        target = self.get_membership()
        return MemberUpdateForm(
            **self.get_form_kwargs(),
            membership=target,
            editing_self=target.pk == self.membership.pk,
        )

    def get_context_data(self, **kwargs):
        return super().get_context_data(target=self.get_membership(), **kwargs)

    def form_valid(self, form):
        try:
            update_member(form=form)
        except QuotaExceeded as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)

        messages.success(self.request, 'Usuário atualizado.')
        return super().form_valid(form)
