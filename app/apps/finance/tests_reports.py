from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.companies.models import Company
from apps.finance import selectors, services
from apps.finance.models import Group, TransactionStatus, TransactionType
from apps.users.models import User

D = Decimal
IN, OUT = TransactionType.INFLOW, TransactionType.OUTFLOW


class ReportsBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127', initial_balance=D('1000.00'))
        self.other = Company.objects.create(name='B', cnpj='11222333000181', initial_balance=D('500.00'))
        self.member.companies.add(self.company)
        sg = services.create_subgroup_service
        self.sales = sg(name='Sales', group=Group.OPERATING_REVENUE)
        self.commission = sg(name='Commission', group=Group.VARIABLE_COSTS)
        self.rent = sg(name='Rent', group=Group.FIXED_COSTS)
        self.interest = sg(name='Interest', group=Group.NON_OPERATING_REVENUE)
        self.fees = sg(name='Bank fees', group=Group.NON_OPERATING_EXPENSES)

    def tx(self, subgroup, amount, type, day, company=None, status=TransactionStatus.REALIZED, **extra):
        return services.create_transaction_service(
            user=self.admin, company_id=(company or self.company).pk, subgroup_id=subgroup.pk,
            date=day, amount=D(amount), type=type, status=status, **extra,
        )


class DRESelectorTest(ReportsBase):
    def setUp(self):
        super().setUp()
        # January 2026
        self.tx(self.sales, '10000', IN, date(2026, 1, 5))
        self.tx(self.sales, '500', OUT, date(2026, 1, 6))        # sales refund (reversal)
        self.tx(self.commission, '1000', OUT, date(2026, 1, 7))
        self.tx(self.rent, '3000', OUT, date(2026, 1, 8))
        self.tx(self.rent, '200', IN, date(2026, 1, 9))          # rent reimbursement (reversal)
        self.tx(self.interest, '100', IN, date(2026, 1, 10))
        self.tx(self.fees, '50', OUT, date(2026, 1, 11))
        # February 2026: only a planned sale
        self.tx(self.sales, '2000', IN, date(2026, 2, 1), status=TransactionStatus.PLANNED)
        # Other year and other company: must not leak
        self.tx(self.sales, '99999', IN, date(2025, 1, 5))
        self.tx(self.rent, '7000', OUT, date(2026, 1, 5), company=self.other)

    def dre(self, user=None, **filters):
        result = selectors.dre_selector(user=user or self.admin, year=2026, **filters)
        return {line['key']: line for line in result['lines']}

    def test_layout_follows_spreadsheet_order(self):
        result = selectors.dre_selector(user=self.admin, year=2026)
        keys = [l['key'] for l in result['lines'] if l['kind'] != 'subgroup']

        self.assertEqual(keys, [
            'group:operating_revenue', 'group:variable_costs', 'contribution_margin',
            'group:fixed_costs', 'profit_margin', 'group:non_operating_revenue',
            'group:non_operating_expenses', 'net_result',
        ])

    def test_subgroups_listed_under_their_group(self):
        result = selectors.dre_selector(user=self.admin, year=2026)
        keys = [l['key'] for l in result['lines']]

        idx = keys.index(f'subgroup:{self.rent.pk}')
        self.assertEqual(keys[idx - 1], 'group:fixed_costs')

    def test_values_with_reversals_and_derived_lines(self):
        lines = self.dre(company_id=[self.company.pk])
        jan = {k: l['months'][0] for k, l in lines.items()}

        self.assertEqual(jan['group:operating_revenue'], D('9500.00'))       # 10000 - 500 refund
        self.assertEqual(jan['group:variable_costs'], D('1000.00'))
        self.assertEqual(jan['contribution_margin'], D('8500.00'))
        self.assertEqual(jan['group:fixed_costs'], D('2800.00'))             # 3000 - 200 reimbursement
        self.assertEqual(jan['profit_margin'], D('5700.00'))
        self.assertEqual(jan['group:non_operating_revenue'], D('100.00'))
        self.assertEqual(jan['group:non_operating_expenses'], D('50.00'))
        self.assertEqual(jan['net_result'], D('5750.00'))

    def test_month_columns_and_year_total(self):
        lines = self.dre(company_id=[self.company.pk])
        revenue = lines['group:operating_revenue']

        self.assertEqual(len(revenue['months']), 12)
        self.assertEqual(revenue['months'][1], D('2000.00'))
        self.assertEqual(revenue['months'][2:], [D('0')] * 10)
        self.assertEqual(revenue['total'], D('11500.00'))

    def test_other_year_is_ignored(self):
        lines = self.dre(company_id=[self.company.pk])

        self.assertNotIn(D('99999.00'), lines['group:operating_revenue']['months'])

    def test_percents_over_operating_revenue(self):
        lines = self.dre(company_id=[self.company.pk])

        self.assertEqual(lines['group:operating_revenue']['percents'][0], D('1.0000'))
        self.assertEqual(lines['contribution_margin']['percents'][0], D('0.8947'))  # 8500 / 9500
        self.assertEqual(lines['net_result']['percents'][0], D('0.6053'))           # 5750 / 9500
        self.assertIsNone(lines['net_result']['percents'][2])                       # no revenue in March
        self.assertEqual(lines['contribution_margin']['total_percent'], D('0.9130'))  # 10500 / 11500

    def test_subgroups_without_movement_are_zero(self):
        idle = services.create_subgroup_service(name='Idle', group=Group.FIXED_COSTS)

        line = self.dre()[f'subgroup:{idle.pk}']

        self.assertEqual(line['months'], [D('0')] * 12)
        self.assertEqual(line['total'], D('0'))

    def test_status_filter(self):
        realized = self.dre(company_id=[self.company.pk], status=[TransactionStatus.REALIZED])
        planned = self.dre(company_id=[self.company.pk], status=[TransactionStatus.PLANNED])

        self.assertEqual(realized['group:operating_revenue']['total'], D('9500.00'))
        self.assertEqual(planned['group:operating_revenue']['total'], D('2000.00'))

    def test_consolidated_includes_all_accessible_companies(self):
        admin = self.dre()
        member = self.dre(user=self.member)

        self.assertEqual(admin['group:fixed_costs']['months'][0], D('9800.00'))   # 2800 + 7000
        self.assertEqual(member['group:fixed_costs']['months'][0], D('2800.00'))

    def test_member_cannot_see_other_company_even_when_filtering_it(self):
        lines = self.dre(user=self.member, company_id=[self.other.pk])

        self.assertEqual(lines['group:fixed_costs']['total'], D('0'))

    def test_subgroup_filter_limits_listed_subgroups(self):
        result = selectors.dre_selector(user=self.admin, year=2026, subgroup_id=[self.rent.pk])
        subgroups = [l['key'] for l in result['lines'] if l['kind'] == 'subgroup']

        self.assertEqual(subgroups, [f'subgroup:{self.rent.pk}'])

    def test_date_filters_and_ordering_are_ignored(self):
        lines = self.dre(
            company_id=[self.company.pk], date_from=date(2026, 6, 1), ordering='-amount'
        )

        self.assertEqual(lines['group:operating_revenue']['total'], D('11500.00'))

    def test_query_count(self):
        with self.assertNumQueries(2):  # aggregation + subgroups
            selectors.dre_selector(user=self.member, year=2026, search='x')


class CashFlowSelectorTest(ReportsBase):
    def setUp(self):
        super().setUp()
        self.tx(self.sales, '300', IN, date(2025, 12, 20))       # before the period
        self.tx(self.rent, '100', OUT, date(2025, 12, 21))       # before the period
        self.tx(self.sales, '1000', IN, date(2026, 1, 10))
        self.tx(self.rent, '400', OUT, date(2026, 1, 15))
        self.tx(self.rent, '50', IN, date(2026, 1, 16))          # reimbursement = real cash in
        self.tx(self.sales, '700', IN, date(2026, 3, 1), status=TransactionStatus.PLANNED)
        self.tx(self.rent, '250', OUT, date(2026, 1, 15), company=self.other)

    def flow(self, user=None, **kwargs):
        params = {'start': date(2026, 1, 1), 'end': date(2026, 3, 31), 'company_id': [self.company.pk]}
        params.update(kwargs)
        return selectors.cash_flow_selector(user=user or self.admin, **params)

    def test_opening_includes_initial_balance_and_prior_movements(self):
        result = self.flow()

        self.assertEqual(result['opening'], D('1200.00'))  # 1000 + 300 - 100

    def test_monthly_periods_chain_and_fill_gaps(self):
        periods = self.flow()['periods']

        self.assertEqual([p['period'] for p in periods], [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])
        jan, feb, mar = periods
        self.assertEqual((jan['opening'], jan['inflow'], jan['outflow'], jan['closing']),
                         (D('1200.00'), D('1050.00'), D('400.00'), D('1850.00')))
        self.assertEqual((feb['opening'], feb['inflow'], feb['outflow'], feb['closing']),
                         (D('1850.00'), D('0'), D('0'), D('1850.00')))
        self.assertEqual(mar['closing'], D('2550.00'))

    def test_closing_equals_last_period(self):
        result = self.flow()

        self.assertEqual(result['closing'], result['periods'][-1]['closing'])

    def test_status_filter_excludes_planned(self):
        result = self.flow(status=[TransactionStatus.REALIZED])

        self.assertEqual(result['closing'], D('1850.00'))

    def test_daily_granularity(self):
        result = self.flow(start=date(2026, 1, 14), end=date(2026, 1, 16), granularity='day')
        periods = result['periods']

        self.assertEqual(result['opening'], D('2200.00'))  # 1200 + 1000 (Jan 10)
        self.assertEqual([p['period'] for p in periods], [date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 16)])
        self.assertEqual([p['closing'] for p in periods], [D('2200.00'), D('1800.00'), D('1850.00')])

    def test_period_starting_mid_month(self):
        result = self.flow(start=date(2026, 1, 12), end=date(2026, 2, 10))

        self.assertEqual(result['opening'], D('2200.00'))
        self.assertEqual(result['periods'][0]['period'], date(2026, 1, 1))
        self.assertEqual(result['periods'][0]['inflow'], D('50.00'))  # only Jan 12..31

    def test_consolidated_sums_initial_balances_of_accessible_companies(self):
        admin = self.flow(company_id=None)
        member = self.flow(user=self.member, company_id=None)

        self.assertEqual(admin['opening'], D('1700.00'))   # 1000 + 500 + 300 - 100
        self.assertEqual(admin['periods'][0]['outflow'], D('650.00'))
        self.assertEqual(member['opening'], D('1200.00'))

    def test_member_filtering_other_company_gets_nothing(self):
        result = self.flow(user=self.member, company_id=[self.other.pk])

        self.assertEqual(result['opening'], D('0'))
        self.assertEqual(result['closing'], D('0'))

    def test_invalid_ranges_raise(self):
        with self.assertRaises(ValidationError):
            self.flow(start=date(2026, 2, 1), end=date(2026, 1, 1))
        with self.assertRaises(ValidationError):
            self.flow(start=date(2025, 1, 1), end=date(2026, 1, 2), granularity='day')  # 367 days

    def test_query_count(self):
        with self.assertNumQueries(3):  # initial balances + before-period + periods
            self.flow(user=self.member, company_id=None, search='x')
