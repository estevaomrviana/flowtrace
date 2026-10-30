from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Organization(TimeStampedModel):
    """Cliente (provedor). Limites e permissões são definidos pela plataforma."""

    name = models.CharField('nome', max_length=150)
    slug = models.SlugField('identificador', max_length=60, unique=True)
    document = models.CharField('CNPJ', max_length=18, blank=True)
    is_active = models.BooleanField(
        'ativa', default=True,
        help_text='Organizações inativas não conseguem acessar o sistema.',
    )

    max_servers = models.PositiveIntegerField(
        'limite de servidores', null=True, blank=True, default=1,
        help_text='Vazio = ilimitado.',
    )
    max_members = models.PositiveIntegerField(
        'limite de usuários', null=True, blank=True, default=5,
        help_text='Vazio = ilimitado.',
    )
    can_manage_servers = models.BooleanField(
        'pode cadastrar servidores', default=False,
        help_text='Se desmarcado, apenas a plataforma cadastra servidores para esta organização.',
    )

    class Meta:
        verbose_name = 'organização'
        verbose_name_plural = 'organizações'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def server_count(self):
        return self.servers.count()

    @property
    def member_count(self):
        return self.memberships.filter(user__is_active=True).count()

    def has_server_quota(self):
        return self.max_servers is None or self.server_count < self.max_servers

    def has_member_quota(self):
        return self.max_members is None or self.member_count < self.max_members


class Membership(TimeStampedModel):
    """Vínculo do usuário com a organização (um usuário pertence a uma organização)."""

    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrador'
        OPERATOR = 'operator', 'Operador'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='membership', verbose_name='usuário',
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE,
        related_name='memberships', verbose_name='organização',
    )
    role = models.CharField('perfil', max_length=20, choices=Role.choices, default=Role.OPERATOR)

    class Meta:
        verbose_name = 'membro'
        verbose_name_plural = 'membros'
        ordering = ['user__first_name', 'user__username']

    def __str__(self):
        return f'{self.user} @ {self.organization}'

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def can_manage_servers(self):
        return self.is_admin and self.organization.can_manage_servers
