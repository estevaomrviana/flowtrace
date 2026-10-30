"""Criptografia simétrica de dados sensíveis (credenciais de servidores).

As chaves vêm de settings.ENCRYPTION_KEYS (lista Fernet). A primeira é usada
para cifrar; todas são aceitas para decifrar, o que permite rotação:
adicione a nova chave no início da lista, rode `manage.py rotate_encryption_keys`
e depois remova a antiga.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver

__all__ = ["Secret", "encrypt", "decrypt", "rotate", "InvalidToken"]

MASK = "••••••••"


class Secret:
    """Valor sensível que não se revela por acidente.

    str(), repr(), templates e logs exibem apenas a máscara; o valor real só é
    obtido explicitamente com .reveal().
    """

    __slots__ = ("_value",)

    def __init__(self, value):
        self._value = value or ""

    def reveal(self):
        return self._value

    def __bool__(self):
        return bool(self._value)

    def __eq__(self, other):
        if isinstance(other, Secret):
            return self._value == other._value
        return NotImplemented

    def __hash__(self):
        return hash(self._value)

    def __str__(self):
        return MASK if self._value else ""

    def __repr__(self):
        return f"<Secret {MASK if self._value else 'vazio'}>"


@lru_cache(maxsize=1)
def _cipher():
    keys = [k for k in getattr(settings, "ENCRYPTION_KEYS", []) if k]
    if not keys:
        raise ImproperlyConfigured("Defina ENCRYPTION_KEYS (ou ENCRYPTION_KEY) no .env")
    try:
        return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
    except ValueError as e:
        raise ImproperlyConfigured(f"Chave de criptografia inválida: {e}") from e


@receiver(setting_changed)
def _reset_cipher(setting, **kwargs):
    if setting in ("ENCRYPTION_KEYS",):
        _cipher.cache_clear()


def encrypt(plaintext):
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(token):
    return _cipher().decrypt(token.encode()).decode()


def rotate(token):
    """Recifra o token com a chave primária atual."""
    return _cipher().rotate(token.encode()).decode()
