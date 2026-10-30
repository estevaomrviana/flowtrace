from django.db import models
from django.db.models.query_utils import DeferredAttribute

from .crypto import InvalidToken, Secret, decrypt, encrypt


class SecretAttribute(DeferredAttribute):
    """Garante que o atributo seja sempre um Secret, mesmo após atribuir texto puro."""

    def __set__(self, instance, value):
        if not isinstance(value, Secret):
            value = Secret(value)
        instance.__dict__[self.field.attname] = value


class EncryptedTextField(models.TextField):
    """Texto cifrado no banco; no Python o valor é sempre um `Secret`.

    - Não é editável por padrão: não aparece em ModelForms nem no admin sem
      que alguém declare explicitamente um campo de formulário write-only.
    - O banco só guarda o token Fernet, nunca o texto puro.
    - dumpdata exporta o token cifrado, não o valor.
    """

    description = "Texto criptografado"
    descriptor_class = SecretAttribute

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("editable", False)
        kwargs.setdefault("blank", True)
        kwargs.setdefault("default", "")
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        for key, default in (("editable", False), ("blank", True), ("default", "")):
            if kwargs.get(key, default) == default:
                kwargs.pop(key, None)
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        if not value:
            return Secret("")
        return Secret(decrypt(value))

    def to_python(self, value):
        if isinstance(value, Secret):
            return value
        if not value:
            return Secret("")
        # Vindo de loaddata, o valor é o token cifrado.
        try:
            return Secret(decrypt(value))
        except InvalidToken:
            return Secret(value)

    def get_prep_value(self, value):
        if isinstance(value, Secret):
            value = value.reveal()
        if not value:
            return ""
        return encrypt(value)

    def value_to_string(self, obj):
        return self.get_prep_value(self.value_from_object(obj))
