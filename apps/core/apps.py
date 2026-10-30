from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'apps.core'
    verbose_name = 'Núcleo'

    def ready(self):
        from . import crypto  # noqa: F401  (registra o reset do cache de chaves)
