from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import (
    Account, Group, Transaction, TransactionEvent, TransactionSeries, TransactionStatus, TransactionType,
)
from apps.finance.services import add_months, split_amount
from apps.users.models import Role, User

D = Decimal


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class SeriesHelpersTest(SimpleTestCase):
    def test_add_months_clamps_to_month_end(self):
        cases = [
            (date(2026, 1, 31), 1, date(2026, 2, 28)),
            (date(2026, 1, 31), 2, date(2026, 3, 31)),   # not chained: back to the 31st
            (date(2028, 1, 31), 1, date(2028, 2, 29)),   # leap year
            (date(2026, 11, 15), 3, date(2027, 2, 15)),  # crosses year
            (date(2026, 5, 10), 0, date(2026, 5, 10)),
            (date(2026, 5, 10), 24, date(2028, 5, 10)),
        ]
        for start, months, expected in cases:
            with self.subTest(start=start, months=months):
                self.assertEqual(add_months(start, months), expected)

    def test_split_amount_is_exact(self):
        cases = [
            (D('30000.00'), 10, [D('3000.00')] * 10),
            (D('100.00'), 3, [D('33.34'), D('33.33'), D('33.33')]),
            (D('0.05'), 3, [D('0.03'), D('0.01'), D('0.01')]),
            (D('1000.01'), 2, [D('500.01'), D('500.00')]),
        ]
        for total, count, expected in cases:
            with self.subTest(total=total, count=count):
                parts = split_amount(total, count)
                self.assertEqual(parts, expected)
                self.assertEqual(sum(parts), total)


class SeriesEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='B', cnpj='11222333000181')
        for user in (self.finance, self.accountant):
            user.companies.add(self.company)
        self.sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.other_account = Account.objects.create(company=self.other_company, name='Bradesco')

    def body(self, **overrides):
        data = {
            'kind': 'installment', 'count': 10, 'first_date': '2026-01-31', 'company_id': self.company.pk,
            'subgroup_id': self.sales.pk, 'type': 'inflow', 'total_amount': '30000.00',
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def post(self, data, user=None):
        return self.client.post('/api/transaction-series', data=data, content_type='application/json',
                                headers=auth_for(user or self.finance))

    def create(self, **overrides):
        response = self.post(self.body(**overrides))
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    # Create

    def test_create_installments(self):
        data = self.create()

        self.assertEqual(data['kind'], 'installment')
        self.assertEqual(data['count'], 10)
        self.assertEqual(D(data['total_amount']), D('30000.00'))
        txs = data['transactions']
        self.assertEqual([t['series_index'] for t in txs], list(range(1, 11)))
        self.assertEqual({D(t['amount']) for t in txs}, {D('3000.00')})
        self.assertEqual([t['date'] for t in txs[:4]], ['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30'])
        self.assertEqual({t['status'] for t in txs}, {'planned'})
        self.assertEqual({t['series_id'] for t in txs}, {data['id']})

    def test_installments_with_uneven_split(self):
        data = self.create(count=3, total_amount='100.00')

        self.assertEqual([D(t['amount']) for t in data['transactions']], [D('33.34'), D('33.33'), D('33.33')])

    def test_create_recurring(self):
        data = self.create(kind='recurring', count=12, total_amount=None, amount='4500.00',
                           subgroup_id=self.rent.pk, type='outflow', first_date='2026-01-05')

        self.assertEqual(data['kind'], 'recurring')
        self.assertEqual(len(data['transactions']), 12)
        self.assertEqual({D(t['amount']) for t in data['transactions']}, {D('4500.00')})
        self.assertEqual(D(data['total_amount']), D('54000.00'))
        self.assertEqual(data['transactions'][-1]['date'], '2026-12-05')

    def test_single_recurring_occurrence_is_allowed(self):
        self.assertEqual(len(self.create(kind='recurring', count=1, total_amount=None, amount='10')['transactions']), 1)

    def test_series_occurrences_appear_in_transaction_list(self):
        series = self.create(count=3, total_amount='300')

        response = self.client.get(f'/api/transaction?company_id={self.company.pk}', headers=auth_for(self.finance))

        items = response.json()['items']
        self.assertEqual(len(items), 3)
        self.assertEqual({i['series_id'] for i in items}, {series['id']})

    def test_create_validation_returns_400(self):
        cases = {
            'installments with amount': self.body(amount='10'),
            'installments without total': self.body(total_amount=None),
            'single installment': self.body(count=1),
            'total too small': self.body(count=3, total_amount='0.02'),
            'recurring with total': self.body(kind='recurring'),
            'recurring without amount': self.body(kind='recurring', total_amount=None),
            'account from another company': self.body(account_id=self.other_account.pk),
            'non existing subgroup': self.body(subgroup_id=999999),
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.post(body).status_code, 400)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(TransactionSeries.objects.exists())

    def test_create_invalid_payload_returns_422(self):
        cases = {
            'count zero': self.body(count=0),
            'count too big': self.body(count=121),
            'negative total': self.body(total_amount='-10'),
            'invalid kind': self.body(kind='weekly'),
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.post(body).status_code, 422)

    def test_create_in_not_linked_company_returns_404(self):
        self.assertEqual(self.post(self.body(company_id=self.other_company.pk)).status_code, 404)

    def test_create_without_permission_returns_403(self):
        self.assertEqual(self.post(self.body(), user=self.accountant).status_code, 403)

    # Get

    def test_get_series(self):
        series = self.create(count=3, total_amount='300')

        response = self.client.get(f'/api/transaction-series/{series["id"]}', headers=auth_for(self.accountant))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t['series_index'] for t in response.json()['transactions']], [1, 2, 3])

    def test_get_series_from_other_company_returns_404(self):
        response = self.post(self.body(company_id=self.other_company.pk), user=self.admin)
        series_id = response.json()['id']

        self.assertEqual(
            self.client.get(f'/api/transaction-series/{series_id}', headers=auth_for(self.finance)).status_code, 404
        )

    # Update "this and following"

    def patch(self, series_id, data, from_index=None, user=None):
        query = f'?from_index={from_index}' if from_index else ''
        return self.client.patch(f'/api/transaction-series/{series_id}{query}', data=data,
                                 content_type='application/json', headers=auth_for(user or self.finance))

    def test_update_from_index(self):
        series = self.create(kind='recurring', count=6, total_amount=None, amount='1000')

        response = self.patch(series['id'], {'amount': '1200.00', 'notes': ' reajuste '}, from_index=4)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['affected'], 3)
        txs = Transaction.objects.filter(series_id=series['id']).order_by('series_index')
        self.assertEqual([t.amount for t in txs], [D('1000')] * 3 + [D('1200')] * 3)
        self.assertEqual(txs[3].notes, 'reajuste')

    def test_update_whole_series(self):
        series = self.create(count=3, total_amount='300')

        self.assertEqual(self.patch(series['id'], {'subgroup_id': self.rent.pk}).json()['affected'], 3)
        self.assertEqual(set(Transaction.objects.values_list('subgroup_id', flat=True)), {self.rent.pk})

    def test_update_does_not_touch_other_series(self):
        a = self.create(count=2, total_amount='200')
        self.create(count=2, total_amount='200')

        self.patch(a['id'], {'notes': 'only a'})

        self.assertEqual(Transaction.objects.filter(notes='only a').count(), 2)

    def test_update_validation(self):
        series = self.create(count=3, total_amount='300')
        cases = {
            'account other company': ({'account_id': self.other_account.pk}, 400),
            'non existing subgroup': ({'subgroup_id': 999999}, 400),
            'zero amount': ({'amount': '0'}, 422),
            'null amount': ({'amount': None}, 422),
        }
        for name, (body, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.patch(series['id'], body).status_code, status)

    def test_update_unlink_contact(self):
        contact = services.create_contact_service(name='Client')
        series = self.create(count=2, total_amount='200', contact_id=contact.pk)

        self.patch(series['id'], {'contact_id': None})

        self.assertFalse(Transaction.objects.filter(contact__isnull=False).exists())

    def test_update_without_permission_returns_403(self):
        series = self.create(count=2, total_amount='200')

        self.assertEqual(self.patch(series['id'], {'notes': 'x'}, user=self.accountant).status_code, 403)

    # Cancel

    def cancel(self, series_id, from_index=None, user=None):
        query = f'?from_index={from_index}' if from_index else ''
        return self.client.delete(f'/api/transaction-series/{series_id}{query}', headers=auth_for(user or self.finance))

    def test_cancel_from_index_keeps_realized(self):
        series = self.create(count=6, total_amount='600')
        Transaction.objects.filter(series_index__in=[1, 2, 5]).update(status=TransactionStatus.REALIZED)

        response = self.cancel(series['id'], from_index=3)

        self.assertEqual(response.json()['affected'], 3)  # 3, 4, 6 (5 is realized)
        remaining = Transaction.objects.filter(series_id=series['id']).order_by('series_index')
        self.assertEqual([t.series_index for t in remaining], [1, 2, 5])

    def test_cancel_everything_removes_series(self):
        series = self.create(count=3, total_amount='300')

        self.assertEqual(self.cancel(series['id']).json()['affected'], 3)
        self.assertFalse(TransactionSeries.objects.exists())

    def test_cancel_keeps_series_while_realized_remain(self):
        series = self.create(count=3, total_amount='300')
        Transaction.objects.filter(series_index=1).update(status=TransactionStatus.REALIZED)

        self.cancel(series['id'])

        self.assertTrue(TransactionSeries.objects.filter(pk=series['id']).exists())

    def test_cancel_other_company_returns_404(self):
        series_id = self.post(self.body(company_id=self.other_company.pk), user=self.admin).json()['id']

        self.assertEqual(self.cancel(series_id).status_code, 404)
        self.assertEqual(Transaction.objects.count(), 10)

    def test_deleting_one_occurrence_keeps_the_rest(self):
        series = self.create(count=3, total_amount='300')
        tx = Transaction.objects.get(series_index=2)

        self.client.delete(f'/api/transaction/{tx.pk}', headers=auth_for(self.finance))

        self.assertEqual(
            list(Transaction.objects.filter(series_id=series['id']).values_list('series_index', flat=True).order_by('series_index')),
            [1, 3],
        )

    # History

    def test_history_records_user_for_bulk_create_update_and_cancel(self):
        series = self.create(count=2, total_amount='200')
        self.patch(series['id'], {'notes': 'x'})
        self.cancel(series['id'])

        labels = list(TransactionEvent.objects.order_by('pgh_id').values_list('pgh_label', flat=True))
        self.assertEqual(labels, ['insert', 'insert', 'update', 'update', 'delete', 'delete'])
        users = {e.pgh_context.metadata['user'] for e in TransactionEvent.objects.all()}
        self.assertEqual(users, {self.finance.pk})
