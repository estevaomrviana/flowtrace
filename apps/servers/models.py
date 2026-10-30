from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedTextField
from apps.core.models import TimeStampedModel


class ServerQuerySet(models.QuerySet):

    def for_organization(self, organization):
        return self.filter(organization=organization)

    def active(self):
        return self.filter(is_active=True)


class Server(TimeStampedModel):
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
    is_active = models.BooleanField('ativo', default=True)
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
