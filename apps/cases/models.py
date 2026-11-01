import json
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel
from apps.core.timezones import TIMEZONE_CHOICES


class CaseQuerySet(models.QuerySet):

    def visible_to(self, membership):
        """Administradores veem toda a organização; operadores, as requisições que abriram."""
        qs = self.filter(organization=membership.organization)
        if not membership.is_admin:
            qs = qs.filter(created_by=membership.user)
        return qs


class Case(TimeStampedModel):
    """Requisição recebida (ofício, mandado) e as consultas feitas para respondê-la."""

    class AuthorityType(models.TextChoices):
        JUDICIARY = 'judiciary', 'Poder Judiciário'
        CIVIL_POLICE = 'civil_police', 'Polícia Civil'
        FEDERAL_POLICE = 'federal_police', 'Polícia Federal'
        PROSECUTOR = 'prosecutor', 'Ministério Público'
        OTHER = 'other', 'Outro'

    class Kind(models.TextChoices):
        COURT_ORDER = 'court_order', 'Ordem judicial'
        ADMINISTRATIVE = 'administrative', 'Requisição administrativa'

    class Status(models.TextChoices):
        OPEN = 'open', 'Em andamento'
        ANSWERED = 'answered', 'Respondida'
        ARCHIVED = 'archived', 'Arquivada'

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT,
        related_name='cases', verbose_name='organização',
    )
    number = models.CharField('nº do ofício / processo', max_length=100)
    authority_type = models.CharField(
        'tipo de órgão', max_length=20, choices=AuthorityType.choices, default=AuthorityType.JUDICIARY,
    )
    authority = models.CharField(
        'órgão requisitante', max_length=200,
        help_text='Ex.: 2ª Vara Criminal de Fortaleza, 4º DP de Caucaia.',
    )
    requester = models.CharField('autoridade signatária', max_length=200, blank=True)
    kind = models.CharField('fundamento', max_length=20, choices=Kind.choices, default=Kind.COURT_ORDER)
    received_on = models.DateField('recebida em', default=timezone.localdate)
    deadline = models.DateField('prazo', null=True, blank=True)
    status = models.CharField('situação', max_length=10, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField('observações internas', blank=True)
    answered_at = models.DateTimeField('respondida em', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='+', verbose_name='aberta por',
    )

    objects = CaseQuerySet.as_manager()

    class Meta:
        verbose_name = 'requisição'
        verbose_name_plural = 'requisições'
        ordering = ['-received_on', '-created_at']
        indexes = [models.Index(fields=['organization', 'status'])]

    def __str__(self):
        return f'{self.number} · {self.authority}'

    @property
    def is_overdue(self):
        return (
            self.deadline is not None
            and self.status == self.Status.OPEN
            and self.deadline < timezone.localdate()
        )

    @property
    def days_left(self):
        if self.deadline is None:
            return None
        return (self.deadline - timezone.localdate()).days

    @property
    def is_editable(self):
        return self.status == self.Status.OPEN


class CaseItem(models.Model):
    """Uma consulta da requisição: IP público + horário (+ porta) como constam no ofício."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        SUCCESS = 'success', 'Concluída'
        NO_LOGS = 'no_logs', 'Sem logs'
        ERROR = 'error', 'Erro'

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name='items', verbose_name='requisição')
    position = models.PositiveIntegerField('ordem')
    server = models.ForeignKey(
        'servers.Server', on_delete=models.SET_NULL, null=True,
        related_name='+', verbose_name='servidor',
    )
    server_name = models.CharField('servidor (registro)', max_length=100)

    ip = models.GenericIPAddressField('IP público', protocol='IPv4')
    port = models.PositiveIntegerField('porta', null=True, blank=True)
    moment = models.DateTimeField('instante consultado')
    input_timezone = models.CharField('fuso informado', max_length=40, choices=TIMEZONE_CHOICES)
    minute_margin = models.PositiveSmallIntegerField('margem (min)', default=5)

    status = models.CharField('situação', max_length=10, choices=Status.choices, default=Status.PENDING)
    result_count = models.PositiveIntegerField('resultados', default=0)
    error_message = models.CharField('erro', max_length=300, blank=True)
    # Snapshot da resposta (fluxos + sessões + cadastro), cifrado: é dado pessoal
    # e é dele que o PDF sai, mesmo que os logs sejam apagados depois.
    result = EncryptedTextField('resultado')
    executed_at = models.DateTimeField('executada em', null=True, blank=True)
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='executada por',
    )

    class Meta:
        verbose_name = 'consulta da requisição'
        verbose_name_plural = 'consultas da requisição'
        ordering = ['position']

    def __str__(self):
        return f'{self.ip}{f":{self.port}" if self.port else ""} @ {self.informed:%d/%m/%Y %H:%M:%S}'

    @property
    def informed(self):
        """O horário como consta no ofício, no fuso informado (naive)."""
        return self.moment.astimezone(ZoneInfo(self.input_timezone)).replace(tzinfo=None)

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def data(self):
        return json.loads(self.result.reveal()) if self.result else None

    @data.setter
    def data(self, value):
        self.result = json.dumps(value, ensure_ascii=False, sort_keys=True) if value is not None else ''


class CaseReport(models.Model):
    """PDF de resposta emitido. Os hashes permitem conferir depois um documento apresentado."""

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name='reports', verbose_name='requisição')
    created_at = models.DateTimeField('emitido em', auto_now_add=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='+', verbose_name='emitido por',
    )
    username = models.CharField('usuário (registro)', max_length=150)
    content_sha256 = models.CharField('hash dos dados', max_length=64)
    file_sha256 = models.CharField('hash do arquivo', max_length=64)
    item_count = models.PositiveIntegerField('consultas')

    class Meta:
        verbose_name = 'relatório emitido'
        verbose_name_plural = 'relatórios emitidos'
        ordering = ['-created_at']

    def __str__(self):
        return f'Relatório {self.pk} · {self.case.number}'

    @property
    def code(self):
        return f'FT-{self.case_id:05d}-{self.pk:04d}'
