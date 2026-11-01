from django.conf import settings
from django.db import models


class SearchLogQuerySet(models.QuerySet):

    def visible_to(self, membership):
        """Administradores veem toda a organização; operadores, apenas as próprias buscas."""
        qs = self.filter(organization=membership.organization)
        if not membership.is_admin:
            qs = qs.filter(user=membership.user)
        return qs


class SearchLog(models.Model):
    """Registro imutável de cada consulta feita na plataforma."""

    class Action(models.TextChoices):
        SEARCH = 'search', 'Busca'
        EXPORT = 'export', 'Exportação CSV'

    class Status(models.TextChoices):
        SUCCESS = 'success', 'Concluída'
        NO_LOGS = 'no_logs', 'Sem logs'
        ERROR = 'error', 'Erro'

    created_at = models.DateTimeField('data', auto_now_add=True, db_index=True)
    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.CASCADE,
        related_name='search_logs', verbose_name='organização',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='+', verbose_name='usuário',
    )
    username = models.CharField('usuário (registro)', max_length=150)
    server = models.ForeignKey(
        'servers.Server', on_delete=models.SET_NULL, null=True,
        related_name='+', verbose_name='servidor',
    )
    server_name = models.CharField('servidor (registro)', max_length=100)

    action = models.CharField('ação', max_length=10, choices=Action.choices, default=Action.SEARCH)
    status = models.CharField('situação', max_length=10, choices=Status.choices)

    query_ip = models.GenericIPAddressField('IP consultado', db_index=True)
    query_port = models.PositiveIntegerField('porta', null=True, blank=True)
    query_datetime = models.DateTimeField('horário consultado')
    query_timezone = models.CharField('fuso informado', max_length=40, blank=True)
    minute_margin = models.PositiveSmallIntegerField('margem (min)')
    case = models.ForeignKey(
        'cases.Case', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='requisição',
    )

    result_count = models.PositiveIntegerField('resultados', default=0)
    error_id = models.CharField('código do erro', max_length=16, blank=True)
    remote_addr = models.GenericIPAddressField('IP do usuário', null=True, blank=True)

    objects = SearchLogQuerySet.as_manager()

    class Meta:
        verbose_name = 'registro de busca'
        verbose_name_plural = 'histórico de buscas'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', '-created_at'])]

    def __str__(self):
        return f'{self.username} → {self.query_ip} ({self.created_at:%d/%m/%Y %H:%M})'
