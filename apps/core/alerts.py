"""Alertas operacionais da plataforma (para a equipe FlowTrace, não para o cliente).

Canais opcionais, configurados por variável de ambiente:
- Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- Healthchecks: HEALTHCHECKS_PING_URL, pingado a cada execução das rotinas
  agendadas (se o ping parar de chegar, o Healthchecks avisa que a rotina parou).

Sem canal configurado, o alerta vai só para o log.
"""
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10


def _post(url, data):
    body = urllib.parse.urlencode(data).encode() if data is not None else b''
    request = urllib.request.Request(url, data=body, method='POST')
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (URL da configuração)
        return response.status


def send_alert(text):
    """Envia o alerta pelos canais configurados. Nunca levanta exceção."""
    logger.warning('ALERTA: %s', text)

    token, chat = settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID
    if not (token and chat):
        return False

    try:
        _post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            {'chat_id': chat, 'text': text, 'disable_web_page_preview': 'true'},
        )
        return True
    except Exception as e:  # noqa: BLE001 - alerta não pode derrubar a rotina
        logger.error('Falha ao enviar alerta pelo Telegram: %s', type(e).__name__)
        return False


def ping_healthcheck(ok=True, details=None):
    """Sinal de vida da rotina agendada (sucesso ou falha) para o Healthchecks."""
    url = settings.HEALTHCHECKS_PING_URL
    if not url:
        return
    target = url.rstrip('/') + ('' if ok else '/fail')
    try:
        request = urllib.request.Request(
            target, data=json.dumps(details or {}).encode(), method='POST',
            headers={'Content-Type': 'application/json'},
        )
        urllib.request.urlopen(request, timeout=TIMEOUT).close()  # noqa: S310
    except Exception as e:  # noqa: BLE001
        logger.error('Falha ao pingar o Healthchecks: %s', type(e).__name__)
