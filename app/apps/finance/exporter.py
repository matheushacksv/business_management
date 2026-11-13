"""Excel export of transactions, in the legacy "Lançamentos" layout (+ system-only columns)."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

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
