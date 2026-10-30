import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='atualizado em')),
                ('name', models.CharField(max_length=150, verbose_name='nome')),
                ('slug', models.SlugField(max_length=60, unique=True, verbose_name='identificador')),
                ('document', models.CharField(blank=True, max_length=18, verbose_name='CNPJ')),
                ('is_active', models.BooleanField(default=True, help_text='Organizações inativas não conseguem acessar o sistema.', verbose_name='ativa')),
                ('max_servers', models.PositiveIntegerField(blank=True, default=1, help_text='Vazio = ilimitado.', null=True, verbose_name='limite de servidores')),
                ('max_members', models.PositiveIntegerField(blank=True, default=5, help_text='Vazio = ilimitado.', null=True, verbose_name='limite de usuários')),
                ('can_manage_servers', models.BooleanField(default=False, help_text='Se desmarcado, apenas a plataforma cadastra servidores para esta organização.', verbose_name='pode cadastrar servidores')),
            ],
            options={
                'verbose_name': 'organização',
                'verbose_name_plural': 'organizações',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Membership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='atualizado em')),
                ('role', models.CharField(choices=[('admin', 'Administrador'), ('operator', 'Operador')], default='operator', max_length=20, verbose_name='perfil')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='organizations.organization', verbose_name='organização')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='membership', to=settings.AUTH_USER_MODEL, verbose_name='usuário')),
            ],
            options={
                'verbose_name': 'membro',
                'verbose_name_plural': 'membros',
                'ordering': ['user__first_name', 'user__username'],
            },
        ),
    ]
