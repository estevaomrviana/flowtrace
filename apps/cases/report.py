"""PDF de resposta à requisição, montado a partir dos snapshots das consultas."""
import io
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.timezones import TIMEZONE_LABELS, utc_offset_label
from apps.servers.services.nfdump_parser import EXACT_MATCH_SECONDS

from .services import item_result

INK = colors.HexColor('#1f2933')
MUTED = colors.HexColor('#616e7c')
RULE = colors.HexColor('#cbd2d9')
SHADE = colors.HexColor('#f0f4f8')

# As fontes padrão do PDF (WinAnsi) não têm alguns símbolos usados na interface.
_REPLACEMENTS = {'−': '-', '→': '->', ' ': ' '}


def _t(value):
    text = '' if value is None else str(value)
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return escape(text)


def _dt(value):
    return value.strftime('%d/%m/%Y %H:%M:%S') if value else '-'


def _tz_text(naive, tz):
    """'UTC' ou 'Fortaleza, UTC-03:00': cidade e deslocamento efetivo naquela data."""
    if tz == 'UTC':
        return 'UTC'
    city = TIMEZONE_LABELS.get(tz, tz).split(' (')[0]
    return f'{city}, {utc_offset_label(naive, tz)}'


def _styles():
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle('title', parent=base['Title'], fontSize=15, leading=19, textColor=INK, spaceAfter=2),
        'subtitle': ParagraphStyle('subtitle', parent=base['Normal'], fontSize=9, textColor=MUTED, alignment=TA_CENTER),
        'h2': ParagraphStyle('h2', parent=base['Heading2'], fontSize=11, leading=14, textColor=INK, spaceBefore=10, spaceAfter=4),
        'body': ParagraphStyle('body', parent=base['Normal'], fontSize=9.5, leading=13, textColor=INK),
        'small': ParagraphStyle('small', parent=base['Normal'], fontSize=8, leading=10.5, textColor=MUTED),
        'cell': ParagraphStyle('cell', parent=base['Normal'], fontSize=8.5, leading=11, textColor=INK),
        'sign': ParagraphStyle('sign', parent=base['Normal'], fontSize=9, leading=12, textColor=INK, alignment=TA_CENTER),
        'sign_small': ParagraphStyle('sign_small', parent=base['Normal'], fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER),
        'mono': ParagraphStyle('mono', parent=base['Normal'], fontName='Courier', fontSize=8, leading=10, textColor=INK),
    }


def _grid(rows, widths, header=False):
    table = Table(rows, colWidths=widths, hAlign='LEFT')
    style = [
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, RULE),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), SHADE))
    else:
        style.append(('BACKGROUND', (0, 0), (0, -1), SHADE))
    table.setStyle(TableStyle(style))
    return table


def build_report(case, items, report, content_sha256, user):
    buffer = io.BytesIO()
    styles = _styles()
    org = case.organization
    issued_at = timezone.localtime(report.created_at)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, _t(f'{org.name} · Relatório {report.code} · emitido em {issued_at:%d/%m/%Y %H:%M}'))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f'Página {doc.page}')
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f'Resposta à requisição {case.number}', author=org.name, creator='FlowTrace',
    )
    p = lambda text, style='body': Paragraph(text, styles[style])  # noqa: E731
    width = doc.width
    story = []

    # Cabeçalho
    story.append(p(f'<b>{_t(org.name)}</b>' + (f' · CNPJ {_t(org.document)}' if org.document else ''), 'subtitle'))
    story.append(Spacer(1, 4 * mm))
    story.append(p('Resposta à requisição de identificação de usuário', 'title'))
    story.append(Spacer(1, 4 * mm))

    story.append(_grid([
        [p('<b>Nº do ofício / processo</b>', 'cell'), p(_t(case.number), 'cell')],
        [p('<b>Órgão requisitante</b>', 'cell'), p(_t(f'{case.authority} ({case.get_authority_type_display()})'), 'cell')],
        *([[p('<b>Autoridade</b>', 'cell'), p(_t(case.requester), 'cell')]] if case.requester else []),
        [p('<b>Fundamento</b>', 'cell'), p(_t(case.get_kind_display()), 'cell')],
        [p('<b>Recebida em</b>', 'cell'), p(case.received_on.strftime('%d/%m/%Y'), 'cell')],
        [p('<b>Emitido em</b>', 'cell'), p(f'{issued_at:%d/%m/%Y %H:%M}', 'cell')],
    ], [45 * mm, width - 45 * mm]))

    story.append(Spacer(1, 5 * mm))
    story.append(p(
        f'Em atendimento à requisição acima, {_t(org.name)} informa o resultado da consulta aos registros '
        f'de conexão e de tradução de endereços (NAT) sob sua guarda, para os {len(items)} '
        f'endereço{"s" if len(items) != 1 else ""} IP e horário{"s" if len(items) != 1 else ""} indicados.'
    ))

    # Consultas
    for item in items:
        story.append(KeepTogether(_item_block(item, styles, width, p)))

    # Metodologia
    margins = sorted({item.minute_margin for item in items})
    story.append(p('Metodologia', 'h2'))
    story.append(p(
        'Para cada endereço IP público e horário informados, foram consultados os registros de tradução de '
        'endereços (CGNAT) do equipamento indicado, numa janela de '
        + ', '.join(f'±{m}' for m in margins) + ' minuto(s) em torno do horário. '
        f'Considera-se correspondência exata o registro com diferença inferior a {EXACT_MATCH_SECONDS} segundos. '
        'Quando informada a porta de origem, apenas o bloco de portas que a contém foi considerado. '
        'O assinante foi identificado pela sessão de autenticação (RADIUS) que detinha o endereço IP privado no '
        'horário consultado. Horários informados em outro fuso foram convertidos para o fuso dos registros, '
        'como indicado em cada item.'
    ))

    # Integridade e assinatura
    story.append(p('Integridade', 'h2'))
    story.append(p(
        'O código abaixo é o resumo criptográfico (SHA-256) dos dados que fundamentam este documento, '
        'mantido no sistema para conferência.', 'small'))
    story.append(Spacer(1, 1.5 * mm))
    story.append(p(content_sha256, 'mono'))

    story.append(Spacer(1, 16 * mm))
    signer = user.get_full_name() or user.get_username()
    story.append(_signature(signer, org.name, styles))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _item_block(item, styles, width, p):
    result = item_result(item)
    block = [p(f'Consulta {item.position}', 'h2')]

    informed = item.informed
    rows = [
        [p('<b>IP público</b>', 'cell'), p(_t(item.ip), 'cell')],
        [p('<b>Porta de origem</b>', 'cell'), p(_t(item.port or 'não informada'), 'cell')],
        [p('<b>Data e hora informadas</b>', 'cell'), p(
            _t(f'{_dt(informed)} ({_tz_text(informed, item.input_timezone)})'), 'cell')],
    ]
    if result and result.target != informed:
        rows.append([p('<b>No fuso dos registros</b>', 'cell'), p(
            _t(f'{_dt(result.target)} ({_tz_text(result.target, result.log_tz)})'), 'cell')])

    if result is None:
        rows.append([p('<b>Resultado</b>', 'cell'), p(_t(_status_text(item)), 'cell')])
        block.append(_grid(rows, [45 * mm, width - 45 * mm]))
        return block

    conclusion = result.conclusion
    rows.append([p('<b>Resultado</b>', 'cell'), p(f'<b>{_t(conclusion.label)}</b>', 'cell')])
    if result.days_missing:
        rows.append([p('<b>Observação</b>', 'cell'), p(_t(
            'Sem registros armazenados para ' + ', '.join(d.strftime('%d/%m/%Y') for d in result.days_missing)
            + '; a janela foi consultada parcialmente.'), 'cell')])
    block.append(_grid(rows, [45 * mm, width - 45 * mm]))

    if conclusion.sessions:
        block.append(Spacer(1, 2 * mm))
        header = [p(f'<b>{h}</b>', 'cell') for h in ('Assinante', 'Dados cadastrais', 'Sessão')]
        body = []
        for s in conclusion.sessions:
            customer = '<br/>'.join(
                f'{_t(k.replace("_", " ").capitalize())}: {_t(v)}' for k, v in s.customer.items() if v
            ) or '-'
            session = (f'IP {_t(s.ip)}<br/>Início {_dt(s.started_at)}<br/>'
                       f'Fim {_dt(s.stopped_at) if s.stopped_at else "sem registro de encerramento"}')
            if s.mac:
                session += f'<br/>MAC {_t(s.mac)}'
            body.append([p(f'Login <b>{_t(s.login)}</b>', 'cell'), p(customer, 'cell'), p(session, 'cell')])
        block.append(_grid([header, *body], [40 * mm, width - 100 * mm, 60 * mm], header=True))
    elif conclusion.private_ips:
        block.append(Spacer(1, 2 * mm))
        block.append(p(_t('Endereço(s) IP privado(s) no horário: ' + ', '.join(conclusion.private_ips)), 'cell'))

    return block


def _status_text(item):
    if item.status == item.Status.NO_LOGS:
        return 'Não há registros armazenados para o período consultado.'
    if item.status == item.Status.ERROR:
        return 'A consulta não pôde ser concluída.'
    return 'Consulta não executada.'


def _signature(name, org_name, styles):
    table = Table(
        [[''], [Paragraph(f'<b>{_t(name)}</b>', styles['sign'])], [Paragraph(_t(org_name), styles['sign_small'])]],
        colWidths=[80 * mm], hAlign='CENTER',
    )
    table.setStyle(TableStyle([
        ('LINEABOVE', (0, 1), (0, 1), 0.6, INK),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
    ]))
    return table
