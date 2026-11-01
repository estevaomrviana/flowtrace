import logging

from .models import SearchLog

logger = logging.getLogger(__name__)


def record_search(*, request, membership, server, query, status, action=SearchLog.Action.SEARCH,
                  result_count=0, error_id='', case=None):
    """Registra a consulta. Falhas no registro não podem derrubar a busca."""
    try:
        return SearchLog.objects.create(
            organization=membership.organization,
            user=request.user,
            username=request.user.get_username(),
            server=server,
            server_name=server.name,
            action=action,
            status=status,
            query_ip=query.ip,
            query_port=query.port,
            query_datetime=query.aware_target,
            query_timezone=query.input_tz,
            minute_margin=query.minute_margin,
            result_count=result_count,
            error_id=error_id,
            remote_addr=request.META.get('REMOTE_ADDR') or None,
            case=case,
        )
    except Exception:
        logger.exception('Falha ao registrar auditoria da busca')
        return None
