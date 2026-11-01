"""Leitura das consultas coladas de um ofício ou planilha, uma por linha.

Formatos aceitos (separador ; , tab ou |):
    203.0.113.1;17/03/2026 16:40:00;51234
    203.0.113.1:51234;2026-03-17 16:40:00
    203.0.113.1	2026-03-17T19:40:00Z
    203.0.113.1;17/03/2026 19:40:00 UTC;51234
"""
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

MAX_LINES = 200

LINE_RE = re.compile(
    r"^\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})(?::(?P<port>\d{1,5}))?\s*[;,\t|]\s*"
    r"(?P<when>[^;,\t|]+?)\s*"
    r"(?:[;,\t|]\s*(?P<port2>\d{1,5})?\s*)?[;,\t|\s]*$"
)

UTC_SUFFIX_RE = re.compile(r"\s*(?:UTC|GMT|Z)\s*$", re.IGNORECASE)

DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y às %H:%M:%S",
    "%d/%m/%Y às %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
)


@dataclass(frozen=True)
class ParsedLine:
    line: int
    ip: str
    port: int | None
    moment: datetime  # aware
    timezone: str  # fuso em que o horário foi informado


@dataclass(frozen=True)
class LineError:
    line: int
    text: str
    message: str


def parse_lines(text, default_tz):
    """Devolve (consultas, erros). Linhas vazias, comentários (#) e cabeçalhos são ignorados."""
    parsed, errors = [], []

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or not any(c.isdigit() for c in line):
            continue

        try:
            parsed.append(_parse_line(number, line, default_tz))
        except ValueError as e:
            errors.append(LineError(number, line[:80], str(e)))

    if len(parsed) > MAX_LINES:
        errors.append(LineError(0, "", f"Máximo de {MAX_LINES} consultas por vez."))

    return parsed, errors


def _parse_line(number, line, default_tz):
    match = LINE_RE.match(line)
    if not match:
        raise ValueError("Formato não reconhecido. Use IP;data e hora;porta.")

    ip = match["ip"]
    try:
        if ipaddress.ip_address(ip).version != 4:
            raise ValueError
    except ValueError:
        raise ValueError(f"IP inválido: {ip}") from None

    if match["port"] and match["port2"] and match["port"] != match["port2"]:
        raise ValueError("Porta informada duas vezes com valores diferentes.")
    port = match["port"] or match["port2"]
    if port is not None:
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError(f"Porta inválida: {port}")

    moment, tz = _parse_moment(match["when"], default_tz)
    return ParsedLine(number, ip, port, moment, tz)


def _parse_moment(text, default_tz):
    """O fuso explícito na linha (UTC, Z, -03:00) prevalece sobre o fuso do lote."""
    text = text.strip()
    if ":" not in text:
        raise ValueError(f"Informe a hora, não só a data: {text}")

    utc_suffix = UTC_SUFFIX_RE.search(text)
    if utc_suffix:
        naive = _parse_naive(text[:utc_suffix.start()])
        return naive.replace(tzinfo=dt_timezone.utc), "UTC"

    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        value = _parse_naive(text)

    if value.tzinfo is not None:
        tz = "UTC" if value.utcoffset().total_seconds() == 0 else default_tz
        return value, tz

    return value.replace(tzinfo=ZoneInfo(default_tz)), default_tz


def _parse_naive(text):
    text = text.strip()
    try:
        value = datetime.fromisoformat(text)
        if value.tzinfo is None:
            return value
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Data e hora não reconhecidas: {text}")
