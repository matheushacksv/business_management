from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Group, TransactionStatus, TransactionType
from apps.users.models import User


class ReportEndpointTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127', initial_balance=Decimal('1000'))
        self.other = Company.objects.create(name='B', cnpj='11222333000181', initial_balance=Decimal('500'))
        member.companies.add(self.company)
        self.auth_admin = {'Authorization': f'Bearer {AccessToken.for_user(admin)}'}  # type:ignore
        self.auth_member = {'Authorization': f'Bearer {AccessToken.for_user(member)}'}  # type:ignore
        sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        for company, subgroup, amount, type, status in [
            (self.company, sales, '1000', TransactionType.INFLOW, TransactionStatus.REALIZED),
            (self.company, rent, '400', TransactionType.OUTFLOW, TransactionStatus.REALIZED),
            (self.company, sales, '300', TransactionType.INFLOW, TransactionStatus.PLANNED),
            (self.other, rent, '250', TransactionType.OUTFLOW, TransactionStatus.REALIZED),
        ]:
            services.create_transaction_service(
                user=admin, company_id=company.pk, subgroup_id=subgroup.pk, date=date(2026, 1, 10),
                amount=Decimal(amount), type=type, status=status,
            )

    def get(self, url, auth=None):
        return self.client.get(url, headers=auth or self.auth_admin)

    def lines(self, response):
        return {l['key']: l for l in response.json()['lines']}

    # Auth

    def test_reports_require_authentication(self):
        for url in ('/api/reports/dre?year=2026', '/api/reports/cash-flow?start=2026-01-01&end=2026-01-31'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 401)

    # DRE

    def test_dre(self):
        response = self.get('/api/reports/dre?year=2026')

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['year'], 2026)
        lines = self.lines(response)
        self.assertEqual(Decimal(lines['group:operating_revenue']['months'][0]), Decimal('1300'))
        self.assertEqual(Decimal(lines['profit_margin']['months'][0]), Decimal('650'))  # 1300 - 650
        self.assertIsNone(lines['profit_margin']['percents'][1])

    def test_dre_with_filters(self):
        response = self.get(
            f'/api/reports/dre?year=2026&company_id={self.company.pk}&status=realized', self.auth_member
        )

        lines = self.lines(response)
        self.assertEqual(Decimal(lines['net_result']['total']), Decimal('600'))  # 1000 - 400

    def test_dre_member_sees_only_own_company(self):
        lines = self.lines(self.get('/api/reports/dre?year=2026', self.auth_member))

        self.assertEqual(Decimal(lines['group:fixed_costs']['total']), Decimal('400'))

    def test_dre_invalid_params_return_422(self):
        for query in ('', 'year=abc', 'year=2026&status=banana'):
            with self.subTest(query=query):
                self.assertEqual(self.get(f'/api/reports/dre?{query}').status_code, 422)

    # Cash flow

    def test_cash_flow(self):
        response = self.get(
            f'/api/reports/cash-flow?start=2026-01-01&end=2026-02-28&company_id={self.company.pk}'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['granularity'], 'month')
        self.assertEqual(Decimal(data['opening']), Decimal('1000'))
        self.assertEqual([p['period'] for p in data['periods']], ['2026-01-01', '2026-02-01'])
        self.assertEqual(Decimal(data['periods'][0]['inflow']), Decimal('1300'))
        self.assertEqual(Decimal(data['closing']), Decimal('1900'))

    def test_cash_flow_daily_realized_only(self):
        response = self.get(
            '/api/reports/cash-flow?start=2026-01-09&end=2026-01-10&granularity=day&status=realized',
            self.auth_member,
        )

        data = response.json()
        self.assertEqual(len(data['periods']), 2)
        self.assertEqual(Decimal(data['closing']), Decimal('1600'))  # 1000 + 1000 - 400

    def test_cash_flow_invalid_range_returns_400(self):
        response = self.get('/api/reports/cash-flow?start=2026-02-01&end=2026-01-01')

        self.assertEqual(response.status_code, 400)

    def test_cash_flow_invalid_params_return_422(self):
        for query in ('start=2026-01-01', 'start=2026-01-01&end=2026-01-31&granularity=week'):
            with self.subTest(query=query):
                self.assertEqual(self.get(f'/api/reports/cash-flow?{query}').status_code, 422)
