import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from django.conf import settings

from apps.core import timezones

from .exceptions import NoLogsFound, RemoteCommandError
from .nfdump_builder import MISSING_DIR_EXIT_CODE, NFDumpCommandBuilder, TimeWindow
from .nfdump_parser import FlowRecord, NFDumpParser
from .ssh_client import SSHClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowQuery:
    ip: str
    target: datetime  # naive, no fuso horário dos logs
    port: int | None = None
    minute_margin: int = 5
    log_tz: str = settings.TIME_ZONE
    input_tz: str = settings.TIME_ZONE  # fuso em que o horário foi informado

    @classmethod
    def from_input(cls, *, ip, informed, input_tz, server, port=None, minute_margin=5):
        """Monta a consulta a partir do horário como consta na requisição."""
        return cls(
            ip=ip,
            target=timezones.convert(informed, input_tz, server.timezone),
            port=port,
            minute_margin=minute_margin,
            log_tz=server.timezone,
            input_tz=input_tz,
        )

    @property
    def window(self):
        return TimeWindow.around(self.target, self.minute_margin)

    @property
    def aware_target(self):
        return timezones.localize(self.target, self.log_tz)

    @property
    def informed(self):
        """O horário como foi informado (no fuso da requisição)."""
        return timezones.convert(self.target, self.log_tz, self.input_tz)

    @property
    def converted(self):
        return self.informed != self.target


@dataclass
class FlowSearchResult:
    query: FlowQuery
    window: TimeWindow
    records: list[FlowRecord] = field(default_factory=list)
    days_searched: list[date] = field(default_factory=list)
    days_missing: list[date] = field(default_factory=list)

    @property
    def exact_count(self):
        return sum(1 for r in self.records if r.is_exact)


class FlowService:

    def __init__(self, server, ssh_factory=None):
        self.server = server
        self.ssh_factory = ssh_factory or SSHClient

    def search(self, query):
        result = FlowSearchResult(query=query, window=query.window)
        records = []

        with self.ssh_factory(self.server) as ssh:
            for day in result.window.days():
                command = NFDumpCommandBuilder.build(
                    self.server.log_path, day, result.window, query.ip
                )
                output = ssh.run(command)

                if output.exit_status == MISSING_DIR_EXIT_CODE:
                    result.days_missing.append(day)
                    continue

                if output.exit_status != 0:
                    raise RemoteCommandError(
                        f"nfdump terminou com código {output.exit_status}: "
                        f"{output.stderr.strip()[:500]}"
                    )

                if output.stderr.strip():
                    logger.warning(
                        "nfdump em %s (%s): %s",
                        self.server, day, output.stderr.strip()[:500],
                    )

                result.days_searched.append(day)
                records.extend(
                    NFDumpParser.parse(output.stdout, query.target, query.port)
                )

        if not result.days_searched:
            raise NoLogsFound(result.days_missing)

        # Remove duplicados mantendo a ordem: mais próximos do horário primeiro.
        unique = dict.fromkeys(records)
        result.records = sorted(
            unique, key=lambda r: (abs(r.delta_seconds), r.flow_time)
        )
        return result
