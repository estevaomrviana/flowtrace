import json
import logging
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from .exceptions import NFDumpOutputError

logger = logging.getLogger(__name__)

# Diferença máxima (em segundos) para considerar o registro no horário exato.
EXACT_MATCH_SECONDS = 60


@dataclass(frozen=True)
class FlowRecord:
    source_ip: str
    flow_time: datetime
    delta_seconds: int  # flow_time - horário consultado
    port_block_start: int | None = None
    port_block_end: int | None = None
    translated_port: int | None = None

    @property
    def is_exact(self):
        return abs(self.delta_seconds) < EXACT_MATCH_SECONDS

    @property
    def match_type(self):
        return "exact_match" if self.is_exact else "near_match"

    @property
    def has_port_block(self):
        return self.port_block_start is not None and self.port_block_end is not None

    def covers_port(self, port):
        if self.has_port_block:
            return self.port_block_start <= port <= self.port_block_end
        if self.translated_port is not None:
            return self.translated_port == port
        return False


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_records(text):
    """Aceita tanto um array JSON (-o json) quanto um objeto por linha (-o json-log)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as e:
            raise NFDumpOutputError(f"Saída do nfdump não é JSON válido: {e}") from e

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise NFDumpOutputError("Saída do nfdump em formato inesperado")
    return data


class NFDumpParser:

    @classmethod
    def parse(cls, json_text, target_datetime, port=None):
        if not json_text or not json_text.strip():
            return []

        records = []
        for item in _load_records(json_text):
            record = cls._parse_item(item, target_datetime)
            if record is None:
                continue
            if port is not None and not record.covers_port(port):
                continue
            records.append(record)

        return records

    @staticmethod
    def _parse_item(item, target_datetime):
        if not isinstance(item, dict):
            return None

        t_first = item.get("t_first")
        source_ip = item.get("src4_addr") or item.get("src6_addr")
        if not t_first or not source_ip:
            return None

        try:
            flow_time = datetime.fromisoformat(t_first)
        except ValueError:
            logger.warning("t_first inválido na saída do nfdump: %r", t_first)
            return None

        if timezone.is_aware(flow_time):
            flow_time = timezone.make_naive(flow_time)
        flow_time = flow_time.replace(microsecond=0)

        return FlowRecord(
            source_ip=source_ip,
            flow_time=flow_time,
            delta_seconds=int((flow_time - target_datetime).total_seconds()),
            port_block_start=_to_int(item.get("pblock_start")),
            port_block_end=_to_int(item.get("pblock_end")),
            translated_port=_to_int(item.get("xsrc_port")),
        )
