import posixpath
import shlex
from dataclasses import dataclass
from datetime import datetime, timedelta

NFDUMP_TIME_FORMAT = "%Y/%m/%d.%H:%M:%S"

# Código de saída usado quando a pasta do dia não existe no servidor.
MISSING_DIR_EXIT_CODE = 3


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    @classmethod
    def around(cls, target, minutes):
        margin = timedelta(minutes=minutes)
        return cls(start=target - margin, end=target + margin)

    def days(self):
        """Dias cobertos pela janela (uma janela perto da meia-noite cobre dois)."""
        day = self.start.date()
        while day <= self.end.date():
            yield day
            day += timedelta(days=1)

    def as_nfdump_range(self):
        return (
            f"{self.start.strftime(NFDUMP_TIME_FORMAT)}-"
            f"{self.end.strftime(NFDUMP_TIME_FORMAT)}"
        )


def quote_path(path):
    """shlex.quote preservando a expansão de "~" no início do caminho."""
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


class NFDumpCommandBuilder:
    """Monta o comando nfdump de um dia. Os logs ficam em <log_path>/AAAA/MM/DD."""

    @staticmethod
    def day_folder(log_path, day):
        return posixpath.join(log_path or ".", day.strftime("%Y/%m/%d"))

    @classmethod
    def build(cls, log_path, day, window, ip):
        folder = quote_path(cls.day_folder(log_path, day))
        time_range = shlex.quote(window.as_nfdump_range())
        filter_rule = shlex.quote(f"xip {ip}")

        return (
            f"test -d {folder} || exit {MISSING_DIR_EXIT_CODE}; "
            f"nfdump -R {folder} -t {time_range} -o json {filter_rule}"
        )
