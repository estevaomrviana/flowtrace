"""Etapa 3/3: remove as colunas antigas de acesso e torna os campos obrigatórios."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servers', '0005_migrate_existing_servers'),
    ]

    operations = [
        migrations.RemoveField(model_name='server', name='username'),
        migrations.RemoveField(model_name='server', name='_password_encrypted'),
        migrations.AlterField(
            model_name='server',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='servers', to='organizations.organization', verbose_name='organização'),
        ),
        migrations.AlterField(
            model_name='server',
            name='name',
            field=models.CharField(max_length=100, verbose_name='nome'),
        ),
        migrations.AlterField(
            model_name='server',
            name='host',
            field=models.CharField(max_length=255, verbose_name='endereço IP ou hostname'),
        ),
        migrations.AlterField(
            model_name='server',
            name='log_path',
            field=models.CharField(help_text='Pasta que contém as subpastas AAAA/MM/DD do nfcapd.', max_length=255, verbose_name='pasta dos logs'),
        ),
        migrations.AlterField(
            model_name='server',
            name='port',
            field=models.PositiveIntegerField(default=22, verbose_name='porta SSH'),
        ),
        migrations.AlterModelOptions(
            name='server',
            options={'ordering': ['name'], 'verbose_name': 'servidor', 'verbose_name_plural': 'servidores'},
        ),
        migrations.AddConstraint(
            model_name='server',
            constraint=models.UniqueConstraint(fields=('organization', 'name'), name='unique_server_name_per_org'),
        ),
    ]
