"""Etapa 2/3: servidores existentes vão para uma organização padrão e a senha
antiga (Fernet com a mesma chave) vira uma ServerCredential."""
from django.db import migrations

from apps.core.crypto import decrypt


def forwards(apps, schema_editor):
    Server = apps.get_model('servers', 'Server')
    ServerCredential = apps.get_model('servers', 'ServerCredential')
    Organization = apps.get_model('organizations', 'Organization')

    servers = list(Server.objects.all())
    if not servers:
        return

    organization, _ = Organization.objects.get_or_create(
        slug='padrao',
        defaults={'name': 'Organização padrão', 'max_servers': None, 'max_members': None},
    )

    seen_names = set()
    for server in servers:
        name = server.name or f'Servidor {server.pk}'
        if name in seen_names:  # nome passa a ser único por organização
            name = f'{name} ({server.pk})'
        seen_names.add(name)

        server.organization = organization
        server.managed_by_platform = True
        server.name = name
        server.host = server.host or ''
        server.log_path = server.log_path or ''
        server.save()

        password = decrypt(server._password_encrypted) if server._password_encrypted else ''
        ServerCredential.objects.create(
            server=server,
            username=server.username or '',
            auth_method='password',
            password=password,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('servers', '0004_server_organization_credential'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
