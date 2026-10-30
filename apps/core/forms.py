from django import forms
from django.contrib.auth.forms import PasswordChangeForm


class StyledFormMixin:
    """Aplica as classes do Bootstrap aos widgets (padrão visual dos formulários)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'form-check-input'
            elif isinstance(widget, forms.Select):
                css = 'form-select'
            else:
                css = 'form-control'
            widget.attrs.setdefault('class', css)


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    """Troca de senha do próprio usuário no padrão visual do sistema."""
