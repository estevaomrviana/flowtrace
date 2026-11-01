"""Fábricas usadas pelos testes dos apps."""
from itertools import count

from django.contrib.auth import get_user_model

_seq = count(1)


def make_organization(**kwargs):
    from apps.organizations.models import Organization

    n = next(_seq)
    kwargs.setdefault('name', f'Provedor {n}')
    kwargs.setdefault('slug', f'provedor-{n}')
    return Organization.objects.create(**kwargs)


def make_member(organization, role='operator', username=None, **kwargs):
    from apps.organizations.models import Membership

    user = get_user_model().objects.create_user(
        username or f'user{next(_seq)}', password='x', **kwargs,
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    return user


def make_server(organization, password='segredo', **kwargs):
    from apps.servers.models import Server, ServerCredential

    kwargs.setdefault('name', f'cgnat-{next(_seq)}')
    kwargs.setdefault('host', '10.0.0.1')
    kwargs.setdefault('log_path', '/logs')
    server = Server.objects.create(organization=organization, **kwargs)
    ServerCredential.objects.create(server=server, username='nf', password=password)
    return server


def raw_column(model, column, pk):
    """Valor gravado no banco, sem passar pelo campo (ex.: token de um campo cifrado)."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {column} FROM {model._meta.db_table} WHERE id = %s', [pk])
        return cursor.fetchone()[0]
