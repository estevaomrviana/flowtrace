from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet


class Server(models.Model):
    name = models.CharField(verbose_name='nome da máquina', max_length=100, null=True, blank=True)
    host = models.CharField(verbose_name='endereço IP ou hostname', max_length=255, null=True, blank=True)
    username = models.CharField(verbose_name='usuário', max_length=100, null=True, blank=True)
    log_path = models.CharField(verbose_name='caminho do arquivo de log', max_length=255, null=True, blank=True)
    port = models.IntegerField(verbose_name='porta', default=22)
    
    _password_encrypted = models.CharField(
        max_length=500, 
        null=True, 
        blank=True, 
        db_column='password',
        verbose_name='senha criptografada'
    )

    class Meta:
        verbose_name = 'Servidor'
        verbose_name_plural = 'Servidores'

    def __str__(self):
        return f"{self.name}"

    @property
    def password(self):
        """Descriptografa a senha ao acessar a propriedade"""
        if self._password_encrypted:
            f = Fernet(settings.ENCRYPTION_KEY.encode())
            return f.decrypt(self._password_encrypted.encode()).decode()
        return None

    @password.setter
    def password(self, value):
        """Criptografa a senha antes de atribuir ao campo do banco"""
        if value:
            f = Fernet(settings.ENCRYPTION_KEY.encode())
            self._password_encrypted = f.encrypt(value.encode()).decode()
        else:
            self._password_encrypted = None


