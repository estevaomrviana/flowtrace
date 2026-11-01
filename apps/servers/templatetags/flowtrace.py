from django import template

from apps.core.timezones import TIMEZONE_LABELS

register = template.Library()


@register.filter
def signed_delta(seconds):
    """Formata a diferença em segundos: 0 → "0s", 75 → "+1m 15s", -3700 → "−1h 01m"."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""

    if seconds == 0:
        return "0s"

    sign = "+" if seconds > 0 else "−"
    minutes, secs = divmod(abs(seconds), 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{sign}{hours}h {minutes:02d}m"
    if minutes:
        return f"{sign}{minutes}m {secs:02d}s"
    return f"{sign}{secs}s"


@register.filter
def tz_label(name):
    """Nome amigável do fuso: "UTC" → "UTC (GMT+0)"."""
    return TIMEZONE_LABELS.get(name, name)


@register.filter
def field_label(name):
    """Coluna da consulta de cadastro como rótulo: "cpf_cnpj" → "Cpf cnpj"."""
    return str(name).replace("_", " ").strip().capitalize()
