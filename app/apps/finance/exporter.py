"""Excel exports: transactions (legacy "Lançamentos" layout + system-only columns) and reports."""

import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HEADERS = [
    'Data', 'Cliente/Fornecedor', 'Valor', 'Tipo', 'Produto/Nº Boleto', 'Grupo', 'Subgrupo',
    'Status', 'Observações', 'Empresa', 'CNPJ', 'Conta', 'Parcela',
]
WIDTHS = {'A': 12, 'B': 32, 'C': 14, 'E': 18, 'F': 26, 'G': 28, 'I': 40, 'J': 24, 'K': 16, 'L': 18}
XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _cell(ws, value, *, number_format=None, font=None):
    cell = WriteOnlyCell(ws, value=value)
    if number_format:
        cell.number_format = number_format
    if font:
        cell.font = font
    return cell


def transactions_xlsx(queryset) -> bytes:
    """`queryset` must select_related company, subgroup, account, contact and series."""
    wb = Workbook(write_only=True)  # streams rows: constant memory for big exports
    ws = wb.create_sheet('Lançamentos')
    for column, width in WIDTHS.items():
        ws.column_dimensions[column].width = width
    bold = Font(bold=True)
    ws.append([_cell(ws, title, font=bold) for title in HEADERS])

    for tx in queryset.iterator(chunk_size=2000):
        ws.append([
            _cell(ws, tx.date, number_format='DD/MM/YYYY'),
            tx.contact.name if tx.contact else '',
            _cell(ws, tx.amount, number_format='#,##0.00'),
            tx.get_type_display(),
            tx.reference,
            tx.subgroup.get_group_display(),
            tx.subgroup.name,
            tx.get_status_display(),
            tx.notes,
            tx.company.name,
            tx.company.cnpj,
            tx.account.name if tx.account else '',
            f'{tx.series_index}/{tx.series.count}' if tx.series_id else '',
        ])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# Reports (DRE views and cash flow): small tables, so a regular styled workbook

MONEY_FORMAT = '#,##0.00;[Red]-#,##0.00'
DELTA_FORMAT = '+#,##0.00;[Red]-#,##0.00;0.00'
PERCENT_FORMAT = '+0.0%;[Red]-0.0%;0.0%'
SHARE_FORMAT = '0.0%;[Red]-0.0%'
GROUP_FILL = PatternFill('solid', fgColor='EEF2F6')
RESULT_FILL = PatternFill('solid', fgColor='E0F2FE')
HEADER_BORDER = Border(bottom=Side(style='thin', color='94A3B8'))


def _report_sheet(title: str, subtitle: str, headers: list[str]):
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\\/*?:\[\]]', '-', title)[:31]  # Excel: no \ / * ? : [ ], max 31 chars
    ws['A1'] = title
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = subtitle
    ws['A2'].font = Font(italic=True, color='64748B')
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.font = Font(bold=True)
        cell.border = HEADER_BORDER
        cell.alignment = Alignment(horizontal='left' if col == 1 else 'right')
    ws.freeze_panes = 'B5'
    ws.column_dimensions['A'].width = 42
    for col in range(2, len(headers) + 1):
        ws.column_dimensions[ws.cell(row=4, column=col).column_letter].width = 16
    return wb, ws


def _save(wb) -> bytes:
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def dre_xlsx(table: dict, subtitle: str, *, percent: bool = False) -> bytes:
    """`table` from dre_table_selector; `percent` exports the share of revenue instead of R$."""
    wb, ws = _report_sheet(table['title'], subtitle, ['Conta'] + [c['label'] for c in table['columns']])
    formats = {'value': SHARE_FORMAT if percent else MONEY_FORMAT, 'delta': DELTA_FORMAT, 'delta_percent': PERCENT_FORMAT}
    for row, line in enumerate(table['lines'], start=5):
        label = ws.cell(row=row, column=1, value=('= ' if line['kind'] == 'result' else '') + line['label'])
        if line['kind'] == 'subgroup':
            label.alignment = Alignment(indent=2)
        for col, column in enumerate(table['columns'], start=2):
            i = col - 2
            use_share = percent and column['kind'] == 'value'
            value = line['percents'][i] if use_share else line['values'][i]
            cell = ws.cell(row=row, column=col, value=value)
            cell.number_format = formats[column['kind']]
        style = {
            'group': (Font(bold=True), GROUP_FILL), 'result': (Font(bold=True), RESULT_FILL),
            'info': (Font(italic=True, color='64748B'), None),
        }.get(line['kind'])
        if style:
            for col in range(1, len(table['columns']) + 2):
                ws.cell(row=row, column=col).font = style[0]
                if style[1]:
                    ws.cell(row=row, column=col).fill = style[1]
    return _save(wb)


def cash_flow_xlsx(flow: dict, subtitle: str) -> bytes:
    daily = flow['granularity'] == 'day'
    title = f"Fluxo de caixa {'diário' if daily else 'mensal'}"
    wb, ws = _report_sheet(title, subtitle, ['Período', 'Saldo inicial', 'Entradas', 'Saídas', 'Saldo final'])
    ws.column_dimensions['A'].width = 16
    for row, period in enumerate(flow['periods'], start=5):
        cell = ws.cell(row=row, column=1, value=period['period'])
        cell.number_format = 'DD/MM/YYYY' if daily else 'MM/YYYY'
        cell.alignment = Alignment(horizontal='left')
        for col, key in enumerate(('opening', 'inflow', 'outflow', 'closing'), start=2):
            ws.cell(row=row, column=col, value=period[key]).number_format = MONEY_FORMAT
    return _save(wb)
