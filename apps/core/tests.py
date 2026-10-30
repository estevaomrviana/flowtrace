from io import StringIO

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from apps.core.testing import make_organization, make_server
from apps.servers.models import ServerCredential

from .crypto import Secret, decrypt, encrypt


def raw_password(credential):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT password FROM {ServerCredential._meta.db_table} WHERE id = %s', [credential.pk],
        )
        return cursor.fetchone()[0]


class SecretTests(SimpleTestCase):

    def test_never_reveals_by_accident(self):
        secret = Secret('hunter2')
        self.assertNotIn('hunter2', str(secret))
        self.assertNotIn('hunter2', repr(secret))
        self.assertNotIn('hunter2', f'{secret}')
        self.assertEqual(secret.reveal(), 'hunter2')

    def test_truthiness(self):
        self.assertFalse(Secret(''))
        self.assertTrue(Secret('x'))

    def test_roundtrip(self):
        self.assertEqual(decrypt(encrypt('abc')), 'abc')


class EncryptedFieldTests(TestCase):

    def test_database_only_stores_ciphertext(self):
        server = make_server(make_organization(), password='s3nha-forte')
        credential = ServerCredential.objects.get(server=server)

        self.assertNotIn('s3nha-forte', raw_password(credential))
        self.assertIsInstance(credential.password, Secret)
        self.assertEqual(credential.password.reveal(), 's3nha-forte')

    def test_assigning_plain_text_keeps_secret_type(self):
        credential = ServerCredential(username='x')
        credential.password = 'abc'
        self.assertIsInstance(credential.password, Secret)

    def test_rotation_command(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()

        with override_settings(ENCRYPTION_KEYS=[old]):
            server = make_server(make_organization(), password='rotacionar')
            credential = server.credential
            token_before = raw_password(credential)

        with override_settings(ENCRYPTION_KEYS=[new, old]):
            call_command('rotate_encryption_keys', stdout=StringIO())

        with override_settings(ENCRYPTION_KEYS=[new]):
            token_after = raw_password(credential)
            self.assertNotEqual(token_before, token_after)
            self.assertEqual(ServerCredential.objects.get(pk=credential.pk).password.reveal(), 'rotacionar')
