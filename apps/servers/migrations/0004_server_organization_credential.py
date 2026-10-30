"""Etapa 1/3: novas colunas (ainda opcionais) e tabela de credenciais."""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.core.fields


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
        ('servers', '0003_alter_server_options'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='server',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='criado em'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='server',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name='atualizado em'),
        ),
        migrations.AddField(
            model_name='server',
            name='organization',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='servers', to='organizations.organization', verbose_name='organização'),
        ),
        migrations.AddField(
            model_name='server',
            name='is_active',
            field=models.BooleanField(default=True, verbose_name='ativo'),
        ),
        migrations.AddField(
            model_name='server',
            name='managed_by_platform',
            field=models.BooleanField(default=False, help_text='Servidores gerenciados pela plataforma não podem ser editados pela organização.', verbose_name='gerenciado pela plataforma'),
        ),
        migrations.AddField(
            model_name='server',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='cadastrado por'),
        ),
        migrations.CreateModel(
            name='ServerCredential',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='atualizado em')),
                ('username', models.CharField(max_length=100, verbose_name='usuário SSH')),
                ('auth_method', models.CharField(choices=[('password', 'Senha'), ('key', 'Chave privada')], default='password', max_length=10, verbose_name='autenticação')),
                ('password', apps.core.fields.EncryptedTextField(verbose_name='senha')),
                ('private_key', apps.core.fields.EncryptedTextField(verbose_name='chave privada')),
                ('key_passphrase', apps.core.fields.EncryptedTextField(verbose_name='senha da chave')),
                ('host_key', models.TextField(blank=True, verbose_name='chave do host')),
                ('host_key_verified_at', models.DateTimeField(blank=True, null=True, verbose_name='chave verificada em')),
                ('server', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='credential', to='servers.server')),
            ],
            options={
                'verbose_name': 'credencial',
                'verbose_name_plural': 'credenciais',
            },
        ),
    ]
