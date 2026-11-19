"""Excel export of commissions (the monthly statement to pay the team)."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from apps.sales.services import commission_amount, tax_rate_for

HEADERS = ['Profissional', 'Tipo', 'Cliente', 'Empresa', 'Data da venda', 'Valor da venda', 'Imposto %',
           'Comissão %', 'Valor fixo', 'Comissão', 'Status', 'Pago em']


def commissions_xlsx(queryset) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = 'Comissões'
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for c in queryset:
        ws.append([
            c.salesperson.name, c.get_kind_display(), c.sale.contact.name if c.sale.contact else '',
            c.sale.company.name, c.sale.date, c.sale.amount, tax_rate_for(c), c.percent, c.fixed_amount,
            commission_amount(c), 'Paga' if c.payment_id else 'A pagar', c.payment.date if c.payment else None,
        ])
    for row in ws.iter_rows(min_row=2):
        row[4].number_format = row[11].number_format = 'DD/MM/YYYY'
        for i in (5, 8, 9):
            row[i].number_format = '#,##0.00'
    for col, width in zip('ABCDEFGHIJKL', (24, 20, 32, 22, 13, 14, 10, 11, 12, 14, 10, 12)):
        ws.column_dimensions[col].width = width
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
