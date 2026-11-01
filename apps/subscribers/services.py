"""Correlação IP privado + horário → assinante, pelo accounting do RADIUS (radacct)."""
import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

from apps.core import timezones
from apps.servers.services.exceptions import FlowSearchError
from apps.servers.services.ssh_client import SSHClient
from apps.servers.services.ssh_tunnel import SSHTunnel

from .models import SubscriberSource

logger = logging.getLogger(__name__)

# A sessão mais recente iniciada até o horário é a única que pode estar com o
# IP naquele momento (um IP só pertence a uma sessão por vez). Sessões mais
# antigas sem acctstoptime são resíduos de quedas sem Accounting-Stop.
SESSION_SQL = (
    "SELECT username, framedipaddress, acctstarttime, acctstoptime, "
    "callingstationid, nasipaddress, acctsessionid "
    "FROM {table} "
    "WHERE framedipaddress = %(ip)s AND acctstarttime <= %(at)s "
    "ORDER BY acctstarttime DESC LIMIT 1"
)

LATEST_SESSION_SQL = (
    "SELECT username, acctstarttime FROM {table} ORDER BY acctstarttime DESC LIMIT 1"
)


class SubscriberSourceError(Exception):
    """Falha ao consultar a fonte de assinantes (conexão, credencial, SQL)."""


@dataclass
class SubscriberSession:
    source: str
    login: str
    ip: str
    started_at: datetime | None  # naive, no fuso pedido na consulta
    stopped_at: datetime | None
    mac: str = ''
    nas_ip: str = ''
    session_id: str = ''
    customer: dict = field(default_factory=dict)

    @property
    def is_open(self):
        """Sem Accounting-Stop: ainda conectado ou a sessão caiu sem registro de fim."""
        return self.stopped_at is None

    def to_dict(self):
        data = asdict(self)
        for key in ('started_at', 'stopped_at'):
            if data[key] is not None:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for key in ('started_at', 'stopped_at'):
            if data.get(key):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)


@dataclass
class LookupResult:
    sessions: dict = field(default_factory=dict)  # ip → [SubscriberSession]
    errors: list = field(default_factory=list)

    def for_ip(self, ip):
        return self.sessions.get(ip, [])


# ---------------------------------------------------------------- Conexão

def _connect_mysql(source, host, port):
    import pymysql

    timeout = settings.SUBSCRIBER_DB_TIMEOUT
    try:
        conn = pymysql.connect(
            host=host, port=port, user=source.db_user, password=source.db_password.reveal(),
            database=source.db_name, charset='utf8mb4', autocommit=True,
            connect_timeout=timeout, read_timeout=timeout, write_timeout=timeout,
        )
        with conn.cursor() as cursor:
            cursor.execute('SET SESSION TRANSACTION READ ONLY')
    except pymysql.MySQLError as e:
        raise SubscriberSourceError(_driver_message(e)) from e
    return conn


def _connect_postgresql(source, host, port):
    import psycopg

    timeout = settings.SUBSCRIBER_DB_TIMEOUT
    try:
        return psycopg.connect(
            host=host, port=port, user=source.db_user, password=source.db_password.reveal(),
            dbname=source.db_name, connect_timeout=timeout, autocommit=True,
            # TimeZone da sessão = fuso da fonte: parâmetros sem fuso e colunas
            # timestamptz (esquema padrão do FreeRADIUS) passam a falar o mesmo horário.
            options=(
                f'-c statement_timeout={timeout * 1000} -c default_transaction_read_only=on '
                f'-c TimeZone={source.timezone}'
            ),
        )
    except psycopg.Error as e:
        raise SubscriberSourceError(_driver_message(e)) from e


DRIVERS = {
    SubscriberSource.Engine.MYSQL: _connect_mysql,
    SubscriberSource.Engine.POSTGRESQL: _connect_postgresql,
}


def _driver_message(error):
    return str(error).strip().splitlines()[0][:300] if str(error).strip() else type(error).__name__


@contextmanager
def connect(source):
    """Conexão somente leitura com o banco da fonte, direta ou pelo túnel SSH."""
    driver = DRIVERS[source.engine]

    if not source.uses_tunnel:
        conn = driver(source, source.db_host, source.db_port)
        try:
            yield conn
        finally:
            conn.close()
        return

    if source.ssh_server is None:
        raise SubscriberSourceError('Túnel SSH sem servidor configurado.')

    try:
        with SSHClient(source.ssh_server) as ssh, SSHTunnel(ssh, source.db_host, source.db_port) as port:
            conn = driver(source, '127.0.0.1', port)
            try:
                yield conn
            finally:
                conn.close()
    except FlowSearchError as e:
        raise SubscriberSourceError(str(e)) from e


# ---------------------------------------------------------------- Consulta

def _as_datetime(value, tz):
    """Horário sem fuso, no fuso da fonte. Colunas com fuso (timestamptz) são convertidas."""
    # MySQL antigo grava "0000-00-00 00:00:00" no lugar de NULL; o PyMySQL devolve texto.
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(ZoneInfo(tz))
    return value.replace(tzinfo=None)


def _rows(cursor):
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _execute(conn, sql, params):
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return _rows(cursor)
    except Exception as e:
        raise SubscriberSourceError(f'Consulta falhou: {_driver_message(e)}') from e


class SubscriberLookup:
    """Consulta as fontes ativas da organização. Falha de uma fonte não derruba as outras."""

    def __init__(self, sources, connector=connect):
        self.sources = list(sources)
        self.connector = connector

    @classmethod
    def for_organization(cls, organization):
        sources = (
            SubscriberSource.objects.for_organization(organization).active()
            .select_related('ssh_server__credential')
        )
        return cls(sources)

    def __bool__(self):
        return bool(self.sources)

    def find(self, ips, at, tz):
        """Quem tinha cada IP no horário `at` (naive, no fuso `tz`)."""
        result = LookupResult()
        ips = list(dict.fromkeys(ips))
        if not ips:
            return result

        for source in self.sources:
            try:
                with self.connector(source) as conn:
                    for ip in ips:
                        session = self._session(conn, source, ip, at, tz)
                        if session is not None:
                            result.sessions.setdefault(ip, []).append(session)
            except SubscriberSourceError as e:
                logger.warning('Fonte de assinantes %s (%s): %s', source, source.organization_id, e)
                result.errors.append(f'{source.name}: {e}')

        return result

    def _session(self, conn, source, ip, at, tz):
        source_at = timezones.convert(at, tz, source.timezone)
        rows = _execute(conn, SESSION_SQL.format(table=source.table), {'ip': ip, 'at': source_at})
        if not rows:
            return None

        row = rows[0]
        started = _as_datetime(row['acctstarttime'], source.timezone)
        stopped = _as_datetime(row['acctstoptime'], source.timezone)
        if stopped is not None and stopped < source_at:
            return None  # o IP já tinha sido liberado nesse horário

        login = str(row['username'] or '')
        return SubscriberSession(
            source=source.name,
            login=login,
            ip=ip,
            started_at=timezones.convert(started, source.timezone, tz) if started else None,
            stopped_at=timezones.convert(stopped, source.timezone, tz) if stopped else None,
            mac=str(row.get('callingstationid') or ''),
            nas_ip=str(row.get('nasipaddress') or ''),
            session_id=str(row.get('acctsessionid') or ''),
            customer=self._customer(conn, source, login),
        )

    @staticmethod
    def _customer(conn, source, login):
        if not source.customer_query or not login:
            return {}
        rows = _execute(conn, source.customer_query, {'login': login})
        if not rows:
            return {}
        return {key: '' if value is None else str(value) for key, value in rows[0].items()}


# ---------------------------------------------------------------- Teste

@dataclass(frozen=True)
class SourceReport:
    ok: bool
    message: str


def check_source(source, connector=connect):
    """Conecta, lê a sessão mais recente e, se houver, testa a consulta de cadastro."""
    try:
        with connector(source) as conn:
            rows = _execute(conn, LATEST_SESSION_SQL.format(table=source.table), {})
            if not rows:
                return SourceReport(True, f'Conexão OK, mas a tabela {source.table} está vazia.')

            latest = rows[0]
            started = _as_datetime(latest['acctstarttime'], source.timezone)
            message = 'Conexão OK.'
            if started:
                message += f' Sessão mais recente iniciada em {started:%d/%m/%Y %H:%M}.'

            if source.customer_query:
                customer = SubscriberLookup._customer(conn, source, str(latest['username'] or ''))
                if customer:
                    message += f' Consulta de cadastro OK ({len(customer)} campos).'
                else:
                    message += ' A consulta de cadastro não retornou dados para o login mais recente.'

            return SourceReport(True, message)
    except SubscriberSourceError as e:
        return SourceReport(False, str(e))
