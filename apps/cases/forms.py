from django import forms
from django.core.exceptions import ValidationError

from apps.core.forms import StyledFormMixin
from apps.core.timezones import TIMEZONE_CHOICES
from apps.servers.forms import MARGIN_CHOICES
from apps.servers.models import Server

from .models import Case
from .parsing import MAX_LINES, parse_lines

LINES_PLACEHOLDER = (
    "203.0.113.1;17/03/2026 16:40:00;51234\n"
    "203.0.113.1:51234;2026-03-17 19:40:00 UTC\n"
    "198.51.100.7\t2026-03-17T19:42:10Z"
)


class CaseForm(StyledFormMixin, forms.ModelForm):

    class Meta:
        model = Case
        fields = (
            "number", "authority_type", "authority", "requester", "kind",
            "received_on", "deadline", "notes",
        )
        widgets = {
            "received_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "deadline": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        received, deadline = cleaned.get("received_on"), cleaned.get("deadline")
        if received and deadline and deadline < received:
            self.add_error("deadline", "O prazo não pode ser anterior ao recebimento.")
        return cleaned


class BatchForm(StyledFormMixin, forms.Form):
    """Consultas coladas do ofício. O fuso é obrigatório e escolhido conscientemente."""

    server = forms.ModelChoiceField(label="Servidor", queryset=Server.objects.none(), empty_label=None)
    timezone = forms.ChoiceField(
        label="Fuso dos horários",
        choices=[("", "Selecione…"), *TIMEZONE_CHOICES],
        help_text="Como consta no ofício. Uma linha com UTC, Z ou -03:00 usa o próprio fuso.",
    )
    minute_margin = forms.TypedChoiceField(label="Margem", choices=MARGIN_CHOICES, coerce=int, initial=5)
    lines = forms.CharField(
        label="Consultas",
        widget=forms.Textarea(attrs={"rows": 6, "spellcheck": "false", "placeholder": LINES_PLACEHOLDER}),
        help_text=f"Uma por linha: IP;data e hora;porta (ou IP:porta;data e hora). Até {MAX_LINES} linhas. "
                  "Pode colar direto de uma planilha.",
    )

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["server"].queryset = Server.objects.for_organization(organization).active()
        self.fields["lines"].widget.attrs["class"] = "form-control mono"
        self.parsed = []

    def clean(self):
        cleaned = super().clean()
        tz, text = cleaned.get("timezone"), cleaned.get("lines")
        if not tz or not text:
            return cleaned

        parsed, errors = parse_lines(text, tz)
        if errors:
            raise ValidationError([
                f"Linha {e.line}: {e.message}" if e.line else e.message for e in errors[:10]
            ] + ([f"… e mais {len(errors) - 10} erro(s)."] if len(errors) > 10 else []))
        if not parsed:
            self.add_error("lines", "Nenhuma consulta encontrada.")
        self.parsed = parsed
        return cleaned
