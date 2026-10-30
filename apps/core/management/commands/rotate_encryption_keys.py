from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.fields import EncryptedTextField


class Command(BaseCommand):
    help = (
        "Recifra todos os campos criptografados com a chave primária "
        "(a primeira de ENCRYPTION_KEYS). Carregar decifra com qualquer chave "
        "da lista; salvar cifra com a primária."
    )

    def handle(self, *args, **options):
        total = 0

        for model in apps.get_models():
            names = [f.name for f in model._meta.fields if isinstance(f, EncryptedTextField)]
            if not names:
                continue

            with transaction.atomic():
                for obj in model._base_manager.select_for_update().iterator():
                    obj.save(update_fields=names)
                    total += 1

            self.stdout.write(f"{model._meta.label}: {', '.join(names)}")

        self.stdout.write(self.style.SUCCESS(f"{total} registro(s) recifrado(s)."))
