from datetime import date
from decimal import Decimal
from io import BytesIO

from django.test import TestCase
from ninja_jwt.tokens import AccessToken
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Group, TransactionStatus, TransactionType
from apps.users.models import User


class DREViewsAndExportTests(TestCase):
    """Comparison views of the DRE and the Excel exports."""

    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127', initial_balance=Decimal('1000'))
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'}  # type:ignore
        sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.rent_id = rent.pk
        for day, subgroup, amount, type in [
            (date(2025, 1, 5), sales, '800', TransactionType.INFLOW),   # same month last year
            (date(2025, 12, 5), sales, '500', TransactionType.INFLOW),  # previous month of Jan/2026
            (date(2026, 1, 5), sales, '1000', TransactionType.INFLOW),
            (date(2026, 1, 6), rent, '400', TransactionType.OUTFLOW),
            (date(2025, 1, 6), rent, '200', TransactionType.OUTFLOW),
        ]:
            services.create_transaction_service(
                user=self.admin, company_id=self.company.pk, subgroup_id=subgroup.pk, date=day,
                amount=Decimal(amount), type=type, status=TransactionStatus.REALIZED,
            )

    def table(self, query):
        response = self.client.get(f'/api/reports/dre/table?{query}', headers=self.auth)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        return data, {l['key']: l for l in data['lines']}

    def test_monthly_view_matches_dre(self):
        data, lines = self.table('year=2026')
        self.assertEqual(len(data['columns']), 13)
        self.assertEqual(data['columns'][-1]['label'], 'Total')
        self.assertEqual(Decimal(lines['group:operating_revenue']['values'][0]), Decimal('1000'))
        self.assertEqual(Decimal(lines['group:operating_revenue']['values'][12]), Decimal('1000'))

    def test_years_view(self):
        data, lines = self.table('view=years&year=2026')
        self.assertEqual([c['label'] for c in data['columns']], ['2025', '2026', 'Variação', 'Var %'])
        revenue = [Decimal(v) for v in lines['group:operating_revenue']['values']]
        self.assertEqual(revenue, [Decimal('1300'), Decimal('1000'), Decimal('-300'), Decimal('-0.2308')])
        rent = lines['group:fixed_costs']
        self.assertEqual(Decimal(rent['values'][3]), Decimal('1'))  # 200 -> 400: +100%
        self.assertEqual(rent['better'], 'down')  # cost going up is bad news
        self.assertEqual(lines['group:operating_revenue']['better'], 'up')
        self.assertEqual(lines['subgroup:%d' % self.rent_id]['better'], 'down')
        # results come right after a cost group but are always "higher is better"
        self.assertEqual(lines['contribution_margin']['better'], 'up')
        self.assertEqual(lines['profit_margin']['better'], 'up')
        self.assertIsNone(rent['percents'][2])

    def test_month_view_january_compares_with_december(self):
        data, lines = self.table('view=month&year=2026&month=1')
        self.assertEqual([c['label'] for c in data['columns']][:3], ['Jan/2025', 'Dez/2025', 'Jan/2026'])
        revenue = lines['group:operating_revenue']['values']
        self.assertEqual([Decimal(v) for v in revenue[:3]], [Decimal('800'), Decimal('500'), Decimal('1000')])
        self.assertEqual(Decimal(revenue[3]), Decimal('1'))     # vs Dec: +100%
        self.assertEqual(Decimal(revenue[4]), Decimal('0.25'))  # vs Jan/2025: +25%

    def test_variation_over_zero_is_null(self):
        _, lines = self.table('view=month&year=2026&month=3')
        self.assertIsNone(lines['group:operating_revenue']['values'][3])

    def test_invalid_view_params(self):
        self.assertEqual(self.client.get('/api/reports/dre/table?view=month&year=2026', headers=self.auth).status_code, 400)
        self.assertEqual(self.client.get('/api/reports/dre/table?view=x&year=2026', headers=self.auth).status_code, 422)

    def test_dre_export_has_the_screen_table(self):
        response = self.client.get('/api/reports/dre/export?view=years&year=2026', headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn('dre-years-2026.xlsx', response['Content-Disposition'])
        ws = load_workbook(BytesIO(response.content)).active
        self.assertEqual(ws['A1'].value, 'DRE 2026 × 2025')
        self.assertIn('Consolidado', ws['A2'].value)
        self.assertEqual([c.value for c in ws[4]], ['Conta', '2025', '2026', 'Variação', 'Var %'])
        rows = {r[0]: r[1:] for r in ws.iter_rows(min_row=5, values_only=True)}
        self.assertEqual(rows['Receitas Operacionais'][:3], (1300, 1000, -300))

    def test_month_view_export(self):
        # "Jan/2026" has a "/", invalid in Excel sheet names
        response = self.client.get('/api/reports/dre/export?view=month&year=2026&month=1&percent=true', headers=self.auth)
        self.assertEqual(response.status_code, 200)
        ws = load_workbook(BytesIO(response.content)).active
        self.assertEqual(ws.title, 'DRE Jan-2026')
        self.assertEqual(ws['A1'].value, 'DRE Jan/2026')

    def test_cash_flow_export(self):
        response = self.client.get(
            f'/api/reports/cash-flow/export?start=2026-01-01&end=2026-02-28&company_id={self.company.pk}',
            headers=self.auth,
        )
        self.assertEqual(response.status_code, 200)
        ws = load_workbook(BytesIO(response.content)).active
        self.assertIn('A', ws['A2'].value)
        rows = list(ws.iter_rows(min_row=5, values_only=True))
        self.assertEqual(len(rows), 2)
        # opening = initial 1000 + 2025 movements (800 + 500 - 200)
        self.assertEqual(rows[0][1:], (2100, 1000, 400, 2700))
