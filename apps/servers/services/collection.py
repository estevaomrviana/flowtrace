"""Saúde da coleta e manifesto de integridade dos arquivos do nfcapd.

Uma rotina agendada (manage.py check_collection, a cada ~5 min) passa por cada
servidor ativo e, numa única conexão:

1. lista os arquivos dos últimos dias (<pasta>/AAAA/MM/DD/nfcapd.AAAAMMDDhhmm);
2. registra no manifesto (LogFile) o SHA-256 de cada arquivo novo e acusa
   arquivos que mudaram depois de registrados;
3. atualiza a situação da coleta (CollectionStatus) e alerta a equipe quando
   o servidor fica sem receber arquivos.

A idade do último arquivo vem do mtime (época Unix), então não depende do fuso.
"""
import logging
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import timezones
from apps.core.alerts import send_alert

from ..models import CollectionStatus, LogFile
from .exceptions import FlowSearchError
from .nfdump_builder import quote_path
from .runner import runner_for

logger = logging.getLogger(__name__)

BASE_MISSING_EXIT = 11
HASH_CHUNK = 200
# Arquivos modificados há menos que isso ainda podem estar sendo gravados/copiados.
SETTLE_SECONDS = 30

FILE_NAME_RE = re.compile(r"nfcapd\.(\d{12})")
SHA256_RE = re.compile(r"^\\?([0-9a-f]{64}) [ *](.+)$")
PATH_RE = re.compile(r"^\d{4}/\d{2}/\d{2}/nfcapd\.\d{12}\S*$")


@dataclass(frozen=True)
class RemoteFile:
    path: str  # relativo à pasta dos logs
    size: int
    modified_at: datetime  # aware (UTC)

    @property
    def mtime(self):
        return int(self.modified_at.timestamp())


@dataclass
class SyncReport:
    state: str
    message: str
    last_file: RemoteFile | None = None
    registered: int = 0
    pending: int = 0
    changed: list = field(default_factory=list)


# ---------------------------------------------------------------- Comandos

def list_command(log_path, days):
    folders = " ".join(shlex.quote(day.strftime("%Y/%m/%d")) for day in days)
    return (
        f"cd {quote_path(log_path)} 2>/dev/null || exit {BASE_MISSING_EXIT}; "
        f'for d in {folders}; do [ -d "$d" ] && '
        f"find \"$d\" -maxdepth 1 -type f -name 'nfcapd.[0-9]*' -printf '%T@ %s %p\\n'; "
        f"done; exit 0"
    )


def hash_command(log_path, paths):
    files = " ".join(shlex.quote(p) for p in paths)
    return f"cd {quote_path(log_path)} || exit {BASE_MISSING_EXIT}; sha256sum -- {files}"


def parse_listing(text):
    files = []
    for line in text.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) != 3 or not PATH_RE.match(parts[2]):
            continue
        try:
            modified = datetime.fromtimestamp(float(parts[0]), tz=dt_timezone.utc)
            size = int(parts[1])
        except ValueError:
            continue
        files.append(RemoteFile(path=parts[2], size=size, modified_at=modified))
    return files


def parse_hashes(text):
    hashes = {}
    for line in text.splitlines():
        match = SHA256_RE.match(line.strip())
        if match:
            hashes[match.group(2)] = match.group(1)
    return hashes


def interval_start(path, tz):
    """Início do intervalo pelo nome (nfcapd.AAAAMMDDhhmm, no fuso do servidor)."""
    match = FILE_NAME_RE.search(path.rsplit("/", 1)[-1])
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group(1), "%Y%m%d%H%M")
    except ValueError:
        return None
    return timezones.localize(naive, tz)


def recent_days(server, now, count):
    today = now.astimezone(ZoneInfo(server.timezone)).date()
    return [today - timedelta(days=i) for i in range(count - 1, -1, -1)]


# ---------------------------------------------------------------- Rotina

def sync_server(server, *, days=2, now=None, runner_factory=None, alert=True):
    """Verifica a coleta e atualiza o manifesto de um servidor. Não levanta exceções."""
    now = now or timezone.now()
    runner_factory = runner_factory or runner_for
    day_list = recent_days(server, now, max(days, 2))

    try:
        with runner_factory(server) as runner:
            result = runner.run(list_command(server.log_path, day_list))
            if result.exit_status == BASE_MISSING_EXIT:
                report = SyncReport(CollectionStatus.State.ERROR, f"A pasta {server.log_path} não existe.")
            elif result.exit_status != 0:
                report = SyncReport(
                    CollectionStatus.State.ERROR,
                    f"A listagem dos arquivos falhou (código {result.exit_status}).",
                )
            else:
                files = parse_listing(result.stdout)
                report = _evaluate(files, now)
                _update_manifest(server, runner, files, day_list, now, report)
    except FlowSearchError as e:
        report = SyncReport(CollectionStatus.State.ERROR, str(e)[:300])
    except Exception:  # noqa: BLE001 - um servidor com problema não para os outros
        logger.exception("Verificação da coleta de %s", server)
        report = SyncReport(CollectionStatus.State.ERROR, "Erro inesperado na verificação.")

    record_status(server, report, now=now, alert=alert)
    return report


def _evaluate(files, now):
    if not files:
        return SyncReport(CollectionStatus.State.EMPTY, "Nenhum arquivo recebido nos últimos dias.")

    last = max(files, key=lambda f: f.modified_at)
    age = now - last.modified_at
    stale_after = timedelta(minutes=settings.COLLECTION_STALE_MINUTES)
    if age > stale_after:
        return SyncReport(
            CollectionStatus.State.STALE,
            f"Último arquivo recebido há {_minutes(age)}.",
            last_file=last,
        )
    return SyncReport(CollectionStatus.State.OK, f"Último arquivo recebido há {_minutes(age)}.", last_file=last)


def _minutes(delta):
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 120:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h"
    return f"{hours // 24} dias"


def _update_manifest(server, runner, files, day_list, now, report):
    known = {}
    for day in day_list:
        prefix = day.strftime("%Y/%m/%d/")
        known.update({
            lf.path: lf for lf in LogFile.objects.filter(server=server, path__startswith=prefix)
        })

    settled_before = now - timedelta(seconds=SETTLE_SECONDS)
    new = [f for f in files if f.path not in known and f.modified_at <= settled_before]
    new.sort(key=lambda f: f.path)

    for f in files:
        entry = known.get(f.path)
        if entry is not None and entry.changed_at is None and (
            entry.size != f.size or int(entry.modified_at.timestamp()) != f.mtime
        ):
            entry.changed_at = now
            entry.save(update_fields=["changed_at"])
            report.changed.append(f.path)

    batch = new[:settings.MANIFEST_BATCH_SIZE]
    report.pending = len(new) - len(batch)

    for start in range(0, len(batch), HASH_CHUNK):
        chunk = batch[start:start + HASH_CHUNK]
        result = runner.run(hash_command(server.log_path, [f.path for f in chunk]))
        hashes = parse_hashes(result.stdout)
        if result.exit_status != 0 and not hashes:
            logger.error("sha256sum em %s terminou com código %s", server, result.exit_status)
            report.pending += len(batch) - start
            break

        LogFile.objects.bulk_create(
            [
                LogFile(
                    server=server,
                    path=f.path,
                    interval_start=interval_start(f.path, server.timezone),
                    size=f.size,
                    modified_at=f.modified_at,
                    sha256=hashes[f.path],
                )
                for f in chunk if f.path in hashes
            ],
            ignore_conflicts=True,
        )
        report.registered += sum(1 for f in chunk if f.path in hashes)

    if report.changed:
        _alert(server, "arquivo(s) alterado(s) depois de registrados no manifesto: " + ", ".join(report.changed[:5])
               + (" …" if len(report.changed) > 5 else ""))


# ---------------------------------------------------------------- Situação e alertas

@transaction.atomic
def record_status(server, report, *, now=None, alert=True):
    now = now or timezone.now()
    status = CollectionStatus.objects.select_for_update().filter(server=server).first()
    was_problem = status is not None and status.is_problem
    status = status or CollectionStatus(server=server)

    status.state = report.state
    status.message = report.message[:300]
    status.checked_at = now
    if report.last_file is not None:
        status.last_file = report.last_file.path[:255]
        status.last_file_at = report.last_file.modified_at

    if status.is_problem:
        if not was_problem:
            status.problem_since = now
        realert = timedelta(hours=settings.COLLECTION_REALERT_HOURS)
        if alert and server.monitor_collection and (status.alerted_at is None or now - status.alerted_at >= realert):
            _alert(server, f"coleta {status.get_state_display().lower()}. {status.message}")
            status.alerted_at = now
    else:
        if status.alerted_at is not None and alert and server.monitor_collection:
            _alert(server, f"coleta normalizada. {status.message}")
        status.problem_since = None
        status.alerted_at = None

    status.save()
    return status


def _alert(server, text):
    send_alert(f"[FlowTrace] {server.organization} / {server}: {text}")


# ---------------------------------------------------------------- Conferência

@dataclass
class VerifyReport:
    checked: int = 0
    mismatched: list = field(default_factory=list)
    missing: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.mismatched and not self.missing


def verify_day(server, day, runner_factory=None):
    """Recalcula o SHA-256 dos arquivos registrados de um dia e compara com o manifesto."""
    runner_factory = runner_factory or runner_for
    entries = {
        lf.path: lf for lf in LogFile.objects.filter(server=server, path__startswith=day.strftime("%Y/%m/%d/"))
    }
    report = VerifyReport()
    if not entries:
        return report

    paths = sorted(entries)
    with runner_factory(server) as runner:
        for start in range(0, len(paths), HASH_CHUNK):
            chunk = paths[start:start + HASH_CHUNK]
            # sha256sum continua nos outros arquivos quando um está faltando.
            hashes = parse_hashes(runner.run(hash_command(server.log_path, chunk)).stdout)
            for path in chunk:
                report.checked += 1
                if path not in hashes:
                    report.missing.append(path)
                elif hashes[path] != entries[path].sha256:
                    report.mismatched.append(path)
    return report


def files_for_window(server, start, end, tz):
    """Arquivos do manifesto que cobrem a janela (horários sem fuso, no fuso dos logs)."""
    rotation = timedelta(seconds=settings.NFCAPD_ROTATION_SECONDS)
    return list(
        LogFile.objects.filter(
            server=server,
            interval_start__gte=timezones.localize(start, tz) - rotation,
            interval_start__lte=timezones.localize(end, tz),
        ).order_by("interval_start", "path")
    )
