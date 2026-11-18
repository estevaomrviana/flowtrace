import posixpath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel
from apps.core.timezones import TIMEZONE_CHOICES


def validate_local_log_path(path):
    """A pasta de um servidor local precisa ficar dentro de FLOWTRACE_DATA_ROOT."""
    root = settings.FLOWTRACE_DATA_ROOT
    if not root:
        raise ValidationError({'access': 'Execução local desligada: defina FLOWTRACE_DATA_ROOT no servidor.'})

    root = posixpath.normpath(root)
    normalized = posixpath.normpath(path or '')
    if not path.startswith('/') or '..' in path.split('/') or not normalized.startswith(root.rstrip('/') + '/'):
        raise ValidationError({'log_path': f'Em execução local, a pasta precisa ficar dentro de {root}/.'})


class ServerQuerySet(models.QuerySet):

    def for_organization(self, organization):
        return self.filter(organization=organization)

    def active(self):
        return self.filter(is_active=True)


class Server(TimeStampedModel):

    class Access(models.TextChoices):
        SSH = 'ssh', 'SSH'
        LOCAL = 'local', 'Execução local'

    organization = models.ForeignKey(
        'organizations.Organization', on_delete=models.PROTECT,
        related_name='servers', verbose_name='organização',
    )
    name = models.CharField('nome', max_length=100)
    host = models.CharField('endereço IP ou hostname', max_length=255)
    port = models.PositiveIntegerField('porta SSH', default=22)
    log_path = models.CharField(
        'pasta dos logs', max_length=255,
        help_text='Pasta que contém as subpastas AAAA/MM/DD do nfcapd.',
    )
    timezone = models.CharField(
        'fuso dos logs', max_length=40, choices=TIMEZONE_CHOICES, default=settings.TIME_ZONE,
        help_text='Fuso horário do servidor que grava os logs (o nfdump exibe os horários nele).',
    )
    access = models.CharField(
        'acesso', max_length=10, choices=Access.choices, default=Access.SSH,
        help_text='Execução local: os logs estão no próprio servidor do flowtrace, dentro da pasta de dados '
                  'da plataforma. Só a plataforma cadastra servidores assim.',
    )
    is_active = models.BooleanField('ativo', default=True)
    monitor_collection = models.BooleanField(
        'monitorar coleta', default=True,
        help_text='Alerta quando o servidor passa muito tempo sem receber arquivos novos. '
                  'Desmarque para servidores que só guardam histórico.',
    )
    managed_by_platform = models.BooleanField(
        'gerenciado pela plataforma', default=False,
        help_text='Servidores gerenciados pela plataforma não podem ser editados pela organização.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='cadastrado por',
    )

    objects = ServerQuerySet.as_manager()

    class Meta:
        verbose_name = 'servidor'
        verbose_name_plural = 'servidores'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_server_name_per_org'),
        ]

    def __str__(self):
        return self.name

    @property
    def is_local(self):
        return self.access == self.Access.LOCAL

    def clean(self):
        super().clean()
        if self.is_local:
            validate_local_log_path(self.log_path)
            # Uma organização não pode apontar um servidor local para os dados de outra.
            self.managed_by_platform = True

    def is_editable_by(self, membership):
        return (
            membership is not None
            and membership.organization_id == self.organization_id
            and membership.can_manage_servers
            and not self.managed_by_platform
        )


class ServerCredential(TimeStampedModel):
    """Acesso SSH ao servidor. Segredos ficam cifrados e nunca voltam para a tela."""

    class AuthMethod(models.TextChoices):
        PASSWORD = 'password', 'Senha'
        KEY = 'key', 'Chave privada'

    server = models.OneToOneField(Server, on_delete=models.CASCADE, related_name='credential')
    username = models.CharField('usuário SSH', max_length=100)
    auth_method = models.CharField(
        'autenticação', max_length=10, choices=AuthMethod.choices, default=AuthMethod.PASSWORD,
    )
    password = EncryptedTextField('senha')
    private_key = EncryptedTextField('chave privada')
    key_passphrase = EncryptedTextField('senha da chave')

    # Chave pública do host aprendida na primeira conexão (trust on first use).
    # Conexões seguintes recusam um host com chave diferente.
    host_key = models.TextField('chave do host', blank=True)
    host_key_verified_at = models.DateTimeField('chave verificada em', null=True, blank=True)

    class Meta:
        verbose_name = 'credencial'
        verbose_name_plural = 'credenciais'

    def __str__(self):
        return f'{self.username}@{self.server}'

    @property
    def has_secret(self):
        if self.auth_method == self.AuthMethod.KEY:
            return bool(self.private_key)
        return bool(self.password)

    def remember_host_key(self, host_key):
        self.host_key = host_key
        self.host_key_verified_at = timezone.now()
        self.save(update_fields=['host_key', 'host_key_verified_at', 'updated_at'])

    def reset_host_key(self):
        self.host_key = ''
        self.host_key_verified_at = None
        self.save(update_fields=['host_key', 'host_key_verified_at', 'updated_at'])


class CollectionStatus(models.Model):
    """Última verificação da chegada de arquivos do nfcapd (manage.py check_collection)."""

    class State(models.TextChoices):
        OK = 'ok', 'Recebendo'
        STALE = 'stale', 'Atrasada'
        EMPTY = 'empty', 'Sem arquivos'
        ERROR = 'error', 'Falha na verificação'

    PROBLEMS = (State.STALE, State.EMPTY, State.ERROR)

    server = models.OneToOneField(Server, on_delete=models.CASCADE, related_name='collection')
    state = models.CharField('situação', max_length=10, choices=State.choices)
    message = models.CharField('mensagem', max_length=300, blank=True)
    checked_at = models.DateTimeField('verificada em')
    last_file_at = models.DateTimeField('último arquivo em', null=True, blank=True)
    last_file = models.CharField('último arquivo', max_length=255, blank=True)
    problem_since = models.DateTimeField('com problema desde', null=True, blank=True)
    alerted_at = models.DateTimeField('alerta enviado em', null=True, blank=True)

    class Meta:
        verbose_name = 'situação da coleta'
        verbose_name_plural = 'situações da coleta'

    def __str__(self):
        return f'{self.server}: {self.get_state_display()}'

    @property
    def is_problem(self):
        return self.state in self.PROBLEMS


class LogFile(models.Model):
    """Manifesto de integridade: hash SHA-256 de cada arquivo do nfcapd, registrado ao chegar.

    Permite afirmar, ao responder um ofício, que o arquivo consultado é o mesmo
    que foi recebido (e detectar quando um arquivo é alterado depois).
    """

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='log_files', verbose_name='servidor')
    path = models.CharField('arquivo', max_length=255, help_text='Relativo à pasta dos logs (AAAA/MM/DD/nfcapd.*).')
    interval_start = models.DateTimeField('início do intervalo', null=True, blank=True)
    size = models.BigIntegerField('tamanho (bytes)')
    modified_at = models.DateTimeField('modificado em')
    sha256 = models.CharField('SHA-256', max_length=64)
    registered_at = models.DateTimeField('registrado em', auto_now_add=True)
    # Preenchido quando o arquivo muda (tamanho ou data) depois de registrado.
    changed_at = models.DateTimeField('alteração detectada em', null=True, blank=True)

    class Meta:
        verbose_name = 'arquivo de log'
        verbose_name_plural = 'arquivos de log'
        ordering = ['server', 'path']
        constraints = [
            models.UniqueConstraint(fields=['server', 'path'], name='unique_log_file_per_server'),
        ]
        indexes = [models.Index(fields=['server', 'interval_start'])]

    def __str__(self):
        return f'{self.server}: {self.path}'
