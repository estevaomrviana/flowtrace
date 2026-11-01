from zoneinfo import ZoneInfo

# Fusos aceitos nos cadastros e nas consultas. Requisições de empresas
# estrangeiras (Google, Meta, etc.) costumam vir em UTC.
TIMEZONE_CHOICES = [
    ('UTC', 'UTC (GMT+0)'),
    ('America/Sao_Paulo', 'Brasília (UTC−3)'),
    ('America/Fortaleza', 'Fortaleza (UTC−3)'),
    ('America/Recife', 'Recife (UTC−3)'),
    ('America/Bahia', 'Salvador (UTC−3)'),
    ('America/Belem', 'Belém (UTC−3)'),
    ('America/Araguaina', 'Palmas (UTC−3)'),
    ('America/Maceio', 'Maceió (UTC−3)'),
    ('America/Noronha', 'Fernando de Noronha (UTC−2)'),
    ('America/Manaus', 'Manaus (UTC−4)'),
    ('America/Cuiaba', 'Cuiabá (UTC−4)'),
    ('America/Campo_Grande', 'Campo Grande (UTC−4)'),
    ('America/Porto_Velho', 'Porto Velho (UTC−4)'),
    ('America/Boa_Vista', 'Boa Vista (UTC−4)'),
    ('America/Rio_Branco', 'Rio Branco (UTC−5)'),
]

TIMEZONE_LABELS = dict(TIMEZONE_CHOICES)


def convert(naive, from_tz, to_tz):
    """Converte um horário "de parede" (sem fuso) de um fuso para outro."""
    aware = naive.replace(tzinfo=ZoneInfo(from_tz))
    return aware.astimezone(ZoneInfo(to_tz)).replace(tzinfo=None)


def localize(naive, tz):
    return naive.replace(tzinfo=ZoneInfo(tz))


def utc_offset_label(naive, tz):
    """'UTC−03:00' para o horário informado no fuso indicado."""
    offset = localize(naive, tz).utcoffset()
    minutes = int(offset.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '−'
    hours, minutes = divmod(abs(minutes), 60)
    return f'UTC{sign}{hours:02d}:{minutes:02d}'
