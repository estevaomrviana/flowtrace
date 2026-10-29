from django import forms
from django.utils import timezone

from .services.flow_service import FlowQuery

MARGIN_CHOICES = [(m, f"± {m} min") for m in (1, 2, 5, 10, 15, 30, 60)]


class FlowSearchForm(forms.Form):

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.update({"class": css})

    def to_query(self):
        data = self.cleaned_data
        return FlowQuery(
            ip=data["ip"],
            target=timezone.make_naive(data["datetime"]),
            port=data["port"],
            minute_margin=data["minute_margin"],
        )
