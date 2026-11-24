"""Excel export of the investments with their position."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

HEADERS = ['Instituição', 'Tipo', 'Descrição', 'Titularidade', 'Empresa', 'Aplicado', 'Resgatado', 'Saldo',
           'Rendimento', 'Rendimento %', 'Saldo informado em', 'Ativo']


def investments_xlsx(items) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = 'Investimentos'
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i in items:
        ws.append([i.institution, i.get_kind_display(), i.description, i.get_holder_display(), i.company.name,
                   i.applied, i.redeemed, i.balance, i.yield_amount, i.yield_percent, i.balance_date,
                   'Sim' if i.active else 'Não'])
    for row in ws.iter_rows(min_row=2):
        for c in row[5:9]:
            c.number_format = '#,##0.00'
        row[10].number_format = 'DD/MM/YYYY'
    for col, width in zip('ABCDEFGHIJKL', (22, 14, 28, 12, 22, 14, 14, 14, 14, 12, 16, 8)):
        ws.column_dimensions[col].width = width
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
