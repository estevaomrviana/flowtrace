import re

from django import forms
from django.core.exceptions import ValidationError

from apps.core.forms import StyledFormMixin
from apps.servers.forms import HOSTNAME_RE
from apps.servers.models import Server

from .models import SubscriberSource

TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
SELECT_RE = re.compile(r"^\s*select\b", re.IGNORECASE)

CUSTOMER_QUERY_EXAMPLE = (
    "SELECT nome, cpf_cnpj AS documento, endereco\n"
    "FROM sis_cliente WHERE login = %(login)s"
)


class SubscriberSourceForm(StyledFormMixin, forms.ModelForm):
    """Fonte + senha do banco. A senha é write-only, como nas credenciais SSH."""

    db_password = forms.CharField(
        label="Senha do banco", required=False, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = SubscriberSource
        fields = (
            "name", "engine", "connection", "ssh_server",
            "db_host", "db_port", "db_name", "db_user",
            "table", "timezone", "customer_query", "is_active",
        )
        widgets = {
            "customer_query": forms.Textarea(attrs={
                "rows": 4, "spellcheck": "false", "placeholder": CUSTOMER_QUERY_EXAMPLE,
            }),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        organization = organization or getattr(self.instance, "organization", None)
        servers = Server.objects.all()
        if organization is not None:
            servers = servers.for_organization(organization)
        self.fields["ssh_server"].queryset = servers
        self.fields["ssh_server"].conditional = True
        self.fields["customer_query"].widget.attrs["class"] = "form-control mono"
        self.fields["customer_query"].help_text = (
            "Opcional. Um SELECT que recebe o login PPPoE em <code>%(login)s</code>; "
            "as colunas retornadas aparecem no resultado e no PDF (use AS para nomeá-las). "
            "Use <code>%%</code> para um % literal."
        )

        if self.instance.pk and self.instance.db_password:
            self.fields["db_password"].help_text = "Deixe em branco para manter o valor salvo."

    def clean_db_host(self):
        host = self.cleaned_data["db_host"].strip()
        if not HOSTNAME_RE.match(host):
            raise ValidationError("Informe um IP ou hostname válido.")
        return host

    def clean_table(self):
        table = self.cleaned_data["table"].strip()
        if not TABLE_RE.match(table):
            raise ValidationError("Use apenas o nome da tabela (ex.: radacct ou esquema.radacct).")
        return table

    def clean_customer_query(self):
        query = self.cleaned_data["customer_query"].strip().rstrip(";").strip()
        if not query:
            return ""
        if not SELECT_RE.match(query):
            raise ValidationError("A consulta deve começar com SELECT.")
        if ";" in query:
            raise ValidationError("Use uma única consulta, sem ponto e vírgula.")
        if "%(login)s" not in query:
            raise ValidationError("A consulta deve usar %(login)s no lugar do login.")
        return query

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("connection") == SubscriberSource.Connection.SSH and not cleaned.get("ssh_server"):
            self.add_error("ssh_server", "Escolha o servidor pelo qual o túnel será aberto.")
        if not cleaned.get("db_password") and not self.instance.db_password:
            self.add_error("db_password", "Informe a senha.")
        return cleaned

    def save(self, commit=True, organization=None, created_by=None):
        source = super().save(commit=False)
        if organization is not None:
            source.organization = organization
        if created_by is not None and not source.pk:
            source.created_by = created_by
        if self.cleaned_data.get("db_password"):
            source.db_password = self.cleaned_data["db_password"]
        if source.connection == SubscriberSource.Connection.DIRECT:
            source.ssh_server = None
        if commit:
            source.save()
        return source
