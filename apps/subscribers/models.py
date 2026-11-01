from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel
from apps.core.timezones import TIMEZONE_CHOICES


class SubscriberSourceQuerySet(models.QuerySet):

    def for_organization(self, organization):
        return self.filter(organization=organization)

    def active(self):
        return self.filter(is_active=True)


class SubscriberSource(TimeStampedModel):
    """Banco do RADIUS (tabela radacct) usado para chegar do IP privado ao assinante."""

    class Engine(models.TextChoices):
        MYSQL = 'mysql', 'MySQL / MariaDB'
        POSTGRESQL = 'postgresql', 'PostgreSQL'

    class Connection(models.TextChoices):
        DIRECT = 'direct', 'Conexão direta'
        SSH = 'ssh', 'Túnel SSH'

    DEFAULT_PORTS = {Engine.MYSQL: 3306, Engine.POSTGRESQL: 5432}

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT,
        related_name='subscriber_sources', verbose_name='organização',
    )
    name = models.CharField('nome', max_length=100)
    engine = models.CharField('banco', max_length=20, choices=Engine.choices, default=Engine.MYSQL)
    connection = models.CharField(
        'acesso', max_length=10, choices=Connection.choices, default=Connection.SSH,
    )
    ssh_server = models.ForeignKey(
        'servers.Server', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='servidor do túnel',
        help_text='O banco é acessado a partir deste servidor, com o mesmo acesso SSH.',
    )

    db_host = models.CharField(
        'host do banco', max_length=255,
        help_text='No túnel SSH, é o endereço visto a partir do servidor (ex.: 127.0.0.1).',
    )
    db_port = models.PositiveIntegerField('porta do banco', default=3306)
    db_name = models.CharField('nome do banco', max_length=100)
    db_user = models.CharField('usuário do banco', max_length=100)
    db_password = EncryptedTextField('senha do banco')

    table = models.CharField('tabela de accounting', max_length=100, default='radacct')
    timezone = models.CharField(
        'fuso do banco', max_length=40, choices=TIMEZONE_CHOICES, default=settings.TIME_ZONE,
        help_text='Fuso em que o RADIUS grava acctstarttime/acctstoptime.',
    )
    customer_query = models.TextField(
        'consulta de cadastro', blank=True,
        help_text='SELECT opcional que recebe o login em %(login)s e devolve os dados do cliente.',
    )

    is_active = models.BooleanField('ativa', default=True)
    managed_by_platform = models.BooleanField('gerenciada pela plataforma', default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='cadastrada por',
    )

    objects = SubscriberSourceQuerySet.as_manager()

    class Meta:
        verbose_name = 'fonte de assinantes'
        verbose_name_plural = 'fontes de assinantes'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_source_name_per_org'),
        ]

    def __str__(self):
        return self.name

    def is_editable_by(self, membership):
        return (
            membership is not None
            and membership.organization_id == self.organization_id
            and membership.can_manage_servers
            and not self.managed_by_platform
        )

    @property
    def uses_tunnel(self):
        return self.connection == self.Connection.SSH
