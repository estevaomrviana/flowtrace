from django import forms


class FlowSearchForm(forms.Form):

    ip = forms.GenericIPAddressField(
        label="IP público",
        protocol="IPv4",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Ex: 203.0.113.1",
                "id": "ip-field",
                "autofocus": True
            }
        )
    )

    datetime = forms.DateTimeField(
        label="Data e hora",
        widget=forms.DateTimeInput(
            attrs={
                "type": "datetime-local"
            }
        ),
        input_formats=["%Y-%m-%dT%H:%M"]
    )

    port = forms.IntegerField(
        label="Porta",
        required=False,
        min_value=1,
        max_value=65535,
        widget=forms.NumberInput(
            attrs={
                "placeholder": "Ex: 1443"
            }
        )
    )

    minute_margin = forms.IntegerField(
        label="Margem de minutos",
        initial=5,
        min_value=1,
        max_value=60
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})
