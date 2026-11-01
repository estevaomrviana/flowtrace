import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.services import record_search
from apps.servers.models import Server
from apps.servers.services.flow_service import FlowQuery
from apps.servers.services.nfdump_parser import FlowRecord
from apps.servers.services.search import run_search
from apps.subscribers.services import SubscriberLookup, SubscriberSession

from .models import CaseItem

STATUS_FROM_SEARCH = {
    'success': CaseItem.Status.SUCCESS,
    'no_logs': CaseItem.Status.NO_LOGS,
    'error': CaseItem.Status.ERROR,
}


# ---------------------------------------------------------------- Inclusão

@transaction.atomic
def add_items(case, lines, *, server, minute_margin):
    start = (case.items.aggregate(n=Max('position'))['n'] or 0) + 1
    return CaseItem.objects.bulk_create([
        CaseItem(
            case=case, position=start + i, server=server, server_name=server.name,
            ip=line.ip, port=line.port, moment=line.moment, input_timezone=line.timezone,
            minute_margin=minute_margin,
        )
        for i, line in enumerate(lines)
    ])


# ---------------------------------------------------------------- Execução

def run_item(item, *, request, membership):
    """Executa a consulta, grava o snapshot do resultado e registra na auditoria."""
    server = (
        Server.objects.for_organization(item.case.organization_id).active()
        .select_related('credential').filter(pk=item.server_id).first()
    )
    item.executed_at = timezone.now()
    item.executed_by = request.user

    if server is None:
        item.status = CaseItem.Status.ERROR
        item.error_message = 'Servidor removido ou inativo. Exclua a consulta e inclua novamente.'
        item.data = None
        item.save()
        return item

    query = FlowQuery.from_input(
        ip=item.ip, informed=item.informed, input_tz=item.input_timezone, server=server,
        port=item.port, minute_margin=item.minute_margin,
    )
    outcome = run_search(server, query, SubscriberLookup.for_organization(item.case.organization))

    record_search(
        request=request, membership=membership, server=server, query=query,
        status=outcome.status, result_count=outcome.result_count, error_id=outcome.error_id,
        case=item.case,
    )

    item.status = STATUS_FROM_SEARCH[outcome.status]
    item.result_count = outcome.result_count
    item.error_message = _error_message(outcome.error)
    item.data = serialize(query, outcome, server) if outcome.result is not None else None
    item.save()
    return item


def _error_message(error):
    if not error:
        return ''
    message = f"{error['title']}: {error['text']}"
    if error.get('id'):
        message += f" (código {error['id']})"
    return message[:300]


# ---------------------------------------------------------------- Snapshot

def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def serialize(query, outcome, server):
    result = outcome.result
    lookup = outcome.subscribers
    return {
        'server': server.name,
        'log_tz': query.log_tz,
        'target': _iso(query.target),
        'window': [_iso(result.window.start), _iso(result.window.end)],
        'days_missing': [_iso(d) for d in result.days_missing],
        'records': [
            {
                'source_ip': r.source_ip,
                'flow_time': _iso(r.flow_time),
                'delta_seconds': r.delta_seconds,
                'port_block_start': r.port_block_start,
                'port_block_end': r.port_block_end,
                'translated_port': r.translated_port,
            }
            for r in result.records
        ],
        'has_sources': lookup is not None,
        'sessions': {
            ip: [s.to_dict() for s in sessions]
            for ip, sessions in (lookup.sessions.items() if lookup else [])
        },
        'subscriber_errors': list(lookup.errors) if lookup else [],
    }


@dataclass
class Conclusion:
    kind: str
    label: str
    css: str
    sessions: list = field(default_factory=list)
    private_ips: list = field(default_factory=list)


@dataclass
class ItemResult:
    """Snapshot de uma consulta reidratado para as telas e o PDF."""

    server: str
    log_tz: str
    target: datetime
    window: tuple
    days_missing: list
    records: list
    sessions: dict
    has_sources: bool
    subscriber_errors: list

    @classmethod
    def from_data(cls, data):
        return cls(
            server=data['server'],
            log_tz=data['log_tz'],
            target=datetime.fromisoformat(data['target']),
            window=tuple(datetime.fromisoformat(v) for v in data['window']),
            days_missing=[date.fromisoformat(d) for d in data['days_missing']],
            records=[
                FlowRecord(**{**r, 'flow_time': datetime.fromisoformat(r['flow_time'])})
                for r in data['records']
            ],
            sessions={
                ip: [SubscriberSession.from_dict(s) for s in sessions]
                for ip, sessions in data['sessions'].items()
            },
            has_sources=data['has_sources'],
            subscriber_errors=data['subscriber_errors'],
        )

    @property
    def rows(self):
        return [(r, self.sessions.get(r.source_ip, [])) for r in self.records]

    @property
    def conclusion(self):
        """Resumo para quem responde: só os registros no horário exato contam."""
        exact = [r for r in self.records if r.is_exact]
        if not self.records:
            return Conclusion('not_found', 'Nenhum registro na janela', 'neutral')
        if not exact:
            return Conclusion('near_only', 'Apenas registros próximos ao horário', 'near')

        private_ips = list(dict.fromkeys(r.source_ip for r in exact))
        if not self.has_sources:
            label = 'IP privado localizado' if len(private_ips) == 1 else 'Mais de um IP privado no horário'
            css = 'info' if len(private_ips) == 1 else 'near'
            return Conclusion('private_only', label, css, private_ips=private_ips)

        unique = {}
        for ip in private_ips:
            for session in self.sessions.get(ip, []):
                unique.setdefault((session.source, session.login), session)
        sessions = list(unique.values())
        unmatched = [ip for ip in private_ips if not self.sessions.get(ip)]

        if not sessions:
            return Conclusion('unmatched', 'IP privado localizado; assinante não encontrado', 'near',
                              private_ips=private_ips)
        if len(sessions) == 1 and not unmatched:
            return Conclusion('identified', 'Assinante identificado', 'exact', sessions, private_ips)
        return Conclusion('ambiguous', 'Mais de um assinante possível', 'near', sessions, private_ips)


def item_result(item):
    data = item.data
    return ItemResult.from_data(data) if data else None


# ---------------------------------------------------------------- Integridade

def content_payload(case, items):
    org = case.organization
    return {
        'organization': {'name': org.name, 'document': org.document},
        'case': {
            'number': case.number,
            'authority': case.authority,
            'authority_type': case.authority_type,
            'kind': case.kind,
            'received_on': _iso(case.received_on),
        },
        'items': [
            {
                'position': item.position,
                'ip': item.ip,
                'port': item.port,
                'moment': _iso(item.moment),
                'input_timezone': item.input_timezone,
                'server': item.server_name,
                'minute_margin': item.minute_margin,
                'status': item.status,
                'executed_at': _iso(item.executed_at),
                'result': item.data,
            }
            for item in items
        ],
    }


def content_hash(case, items):
    """SHA-256 dos dados que sustentam o relatório, em JSON canônico."""
    raw = json.dumps(content_payload(case, items), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()
