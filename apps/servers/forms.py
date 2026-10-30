import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.forms import StyledFormMixin

from .models import Server, ServerCredential
from .services.flow_service import FlowQuery
from .services.ssh_client import load_private_key

MARGIN_CHOICES = [(m, f"± {m} min") for m in (1, 2, 5, 10, 15, 30, 60)]

HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,253}[A-Za-z0-9])?$")


class FlowSearchForm(StyledFormMixin, forms.Form):

    ip = forms.GenericIPAddressField(
        label="IP público",
        protocol="IPv4",
        widget=forms.TextInput(
            attrs={
                "placeholder": "203.0.113.1",
                "inputmode": "decimal",
                "autocomplete": "off",
                "spellcheck": "false",
                "autofocus": True,
            }
        ),
    )

    datetime = forms.DateTimeField(
        label="Data e hora",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "step": 1},
            format="%Y-%m-%dT%H:%M:%S",
        ),
        input_formats=["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"],
    )

    port = forms.IntegerField(
        label="Porta",
        required=False,
        min_value=1,
        max_value=65535,
        widget=forms.NumberInput(attrs={"placeholder": "Opcional"}),
    )

    minute_margin = forms.TypedChoiceField(
        label="Margem",
        choices=MARGIN_CHOICES,
        coerce=int,
        initial=5,
    )

    def to_query(self):
        data = self.cleaned_data
        return FlowQuery(
            ip=data["ip"],
            target=timezone.make_naive(data["datetime"]),
            port=data["port"],
            minute_margin=data["minute_margin"],
        )


class ServerForm(StyledFormMixin, forms.ModelForm):
    """Servidor + credencial SSH. Os segredos são write-only: nunca são
    renderizados de volta e, deixados em branco, mantêm o valor salvo."""

    username = forms.CharField(label="Usuário SSH", max_length=100)
    auth_method = forms.ChoiceField(
        label="Autenticação", choices=ServerCredential.AuthMethod.choices,
        initial=ServerCredential.AuthMethod.PASSWORD,
    )
    password = forms.CharField(
        label="Senha", required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    private_key = forms.CharField(
        label="Chave privada", required=False, strip=False,
        widget=forms.Textarea(attrs={
            "rows": 5, "spellcheck": "false", "autocomplete": "off",
            "placeholder": "-----BEGIN OPENSSH PRIVATE KEY-----",
        }),
    )
    key_passphrase = forms.CharField(
        label="Senha da chave", required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Apenas se a chave for protegida por senha.",
    )

    class Meta:
        model = Server
        fields = ("name", "host", "port", "log_path", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.credential = getattr(self.instance, "credential", None) if self.instance.pk else None

        if self.credential:
            self.fields["username"].initial = self.credential.username
            self.fields["auth_method"].initial = self.credential.auth_method
            keep = "Deixe em branco para manter o valor salvo."
            if self.credential.password:
                self.fields["password"].help_text = keep
            if self.credential.private_key:
                self.fields["private_key"].help_text = keep
                self.fields["private_key"].widget.attrs["placeholder"] = "Chave salva (oculta)"

        self.fields["private_key"].widget.attrs["class"] = "form-control mono"

        # Obrigatórios conforme o método de autenticação (validado em clean()).
        self.fields["password"].conditional = True
        self.fields["private_key"].conditional = True

    def clean_host(self):
        host = self.cleaned_data["host"].strip()
        if not HOSTNAME_RE.match(host):
            raise ValidationError("Informe um IP ou hostname válido.")
        return host

    def clean_log_path(self):
        path = self.cleaned_data["log_path"].strip()
        if any(c in path for c in "\0\n\r"):
            raise ValidationError("Caminho inválido.")
        if not (path.startswith("/") or path.startswith("~")):
            raise ValidationError("Use um caminho absoluto (ex.: /var/cache/nfdump).")
        return path.rstrip("/") or "/"

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("auth_method")
        cred = self.credential

        if method == ServerCredential.AuthMethod.PASSWORD:
            if not cleaned.get("password") and not (cred and cred.password):
                self.add_error("password", "Informe a senha.")

        elif method == ServerCredential.AuthMethod.KEY:
            key = cleaned.get("private_key") or (cred.private_key.reveal() if cred else "")
            passphrase = cleaned.get("key_passphrase") or (cred.key_passphrase.reveal() if cred else "")
            if not key:
                self.add_error("private_key", "Informe a chave privada.")
            elif cleaned.get("private_key") or cleaned.get("key_passphrase"):
                try:
                    load_private_key(key.strip() + "\n", passphrase)
                except ValueError as e:
                    self.add_error("private_key", str(e))

        return cleaned

    def save(self, commit=True, organization=None, created_by=None):
        server = super().save(commit=False)
        if organization is not None:
            server.organization = organization
        if created_by is not None and not server.pk:
            server.created_by = created_by
        if commit:
            server.save()
            self.save_credential()
        return server

    def save_credential(self):
        data = self.cleaned_data
        cred = self.credential or ServerCredential(server=self.instance)

        # Mudou o destino: a chave do host aprendida não vale mais.
        if self.instance.pk and {"host", "port"} & set(self.changed_data):
            cred.host_key = ""
            cred.host_key_verified_at = None

        cred.username = data["username"]
        cred.auth_method = data["auth_method"]
        if data.get("password"):
            cred.password = data["password"]
        if data.get("private_key"):
            cred.private_key = data["private_key"].strip() + "\n"
        if data.get("key_passphrase"):
            cred.key_passphrase = data["key_passphrase"]

        # Não guarda segredo que não está em uso.
        if cred.auth_method == ServerCredential.AuthMethod.PASSWORD:
            cred.private_key = ""
            cred.key_passphrase = ""
        else:
            cred.password = ""

        cred.save()
        self.credential = cred
        return cred
