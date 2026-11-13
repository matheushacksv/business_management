from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Account, Group, Transaction, TransactionType
from apps.users.models import User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class TransactionEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='Company A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='Company B', cnpj='11222333000181')
        member.companies.add(self.company)
        self.auth_admin = auth_for(self.admin)
        self.auth_member = auth_for(member)
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.account = Account.objects.create(company=self.company, name='Itaú')
        self.other_account = Account.objects.create(company=self.other_company, name='Bradesco')
        self.tx = self.create()
        self.other_tx = self.create(company=self.other_company)

    def create(self, company=None, **overrides):
        data = {
            'company_id': (company or self.company).pk, 'subgroup_id': self.rent.pk,
            'date': date(2026, 1, 10), 'amount': Decimal('100.00'), 'type': TransactionType.OUTFLOW,
        }
        data.update(overrides)
        return services.create_transaction_service(user=self.admin, **data)

    def body(self, **overrides):
        data = {
            'company_id': self.company.pk, 'subgroup_id': self.rent.pk,
            'date': '2026-01-15', 'amount': '290.40', 'type': 'outflow',
        }
        data.update(overrides)
        return data

    def post(self, data, auth=None):
        return self.client.post(
            '/api/transaction', data=data, content_type='application/json', headers=auth or self.auth_member
        )

    def patch(self, tx_id, data, auth=None):
        return self.client.patch(
            f'/api/transaction/{tx_id}', data=data, content_type='application/json',
            headers=auth or self.auth_member,
        )

    # Auth

    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/api/transaction').status_code, 401)

    # Create

    def test_create_transaction(self):
        response = self.post(self.body())

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(Decimal(data['amount']), Decimal('290.40'))
        self.assertEqual(data['status'], 'planned')
        self.assertEqual(data['group'], 'fixed_costs')
        self.assertFalse(data['is_reversal'])
        self.assertTrue(Transaction.objects.filter(pk=data['id']).exists())

    def test_create_reversal_transaction(self):
        response = self.post(self.body(type='inflow'))

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['is_reversal'])

    def test_create_transaction_invalid_payload_returns_422(self):
        cases = {
            'zero amount': self.body(amount='0'),
            'negative amount': self.body(amount='-10'),
            'too many decimals': self.body(amount='10.123'),
            'invalid type': self.body(type='banana'),
            'invalid status': self.body(status='banana'),
            'invalid date': self.body(date='2026-13-01'),
            'missing subgroup': {k: v for k, v in self.body().items() if k != 'subgroup_id'},
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.post(data).status_code, 422)

    def test_create_transaction_in_not_linked_company_returns_404(self):
        response = self.post(self.body(company_id=self.other_company.pk))

        self.assertEqual(response.status_code, 404)

    def test_create_transaction_with_account_from_another_company_returns_400(self):
        response = self.post(self.body(account_id=self.other_account.pk))

        self.assertEqual(response.status_code, 400)

    def test_create_transaction_with_non_existing_subgroup_returns_400(self):
        self.assertEqual(self.post(self.body(subgroup_id=999999)).status_code, 400)

    # List

    def test_list_is_paginated(self):
        response = self.client.get('/api/transaction', headers=self.auth_admin)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 2)
        self.assertCountEqual([t['id'] for t in data['items']], [self.tx.pk, self.other_tx.pk])

    def test_list_page_size(self):
        for _ in range(55):
            self.create()

        response = self.client.get('/api/transaction?page=2', headers=self.auth_member)

        data = response.json()
        self.assertEqual(data['count'], 56)
        self.assertEqual(len(data['items']), 6)

    def test_member_lists_only_linked_transactions(self):
        response = self.client.get('/api/transaction', headers=self.auth_member)

        self.assertEqual([t['id'] for t in response.json()['items']], [self.tx.pk])

    def test_list_with_filters(self):
        feb = self.create(date=date(2026, 2, 10))

        response = self.client.get(
            f'/api/transaction?company_id={self.company.pk}&date_from=2026-02-01&group=fixed_costs',
            headers=self.auth_admin,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t['id'] for t in response.json()['items']], [feb.pk])

    def test_list_with_invalid_filter_returns_422(self):
        response = self.client.get('/api/transaction?status=banana', headers=self.auth_admin)

        self.assertEqual(response.status_code, 422)

    def ids(self, query, auth=None):
        response = self.client.get(f'/api/transaction?{query}', headers=auth or self.auth_admin)
        self.assertEqual(response.status_code, 200, response.content)
        return [t['id'] for t in response.json()['items']]

    def test_list_multi_value_query_params(self):
        sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        tx_sales = self.create(subgroup_id=sales.pk, type=TransactionType.INFLOW)

        result = self.ids(f'company_id={self.company.pk}&company_id={self.other_company.pk}')
        self.assertCountEqual(result, [self.tx.pk, self.other_tx.pk, tx_sales.pk])

        result = self.ids('group=operating_revenue&group=variable_costs')
        self.assertEqual(result, [tx_sales.pk])

        result = self.ids('status=planned&status=realized&type=inflow')
        self.assertEqual(result, [tx_sales.pk])

    def test_list_amount_range_and_search(self):
        target = self.create(amount=Decimal('750.00'), notes='Aluguel escritório')
        self.create(amount=Decimal('750.00'), notes='Internet')
        self.create(amount=Decimal('9000.00'), notes='Aluguel galpão')

        result = self.ids('amount_min=500&amount_max=1000&search=aluguel')

        self.assertEqual(result, [target.pk])

    def test_list_ordering(self):
        big = self.create(amount=Decimal('9999.00'))

        self.assertEqual(self.ids('ordering=-amount')[0], big.pk)

    def test_list_invalid_params_return_422(self):
        cases = {
            'ordering': 'ordering=company__cnpj',
            'group in list': 'group=fixed_costs&group=banana',
            'amount': 'amount_min=abc',
            'company id': 'company_id=abc',
        }
        for name, query in cases.items():
            with self.subTest(case=name):
                response = self.client.get(f'/api/transaction?{query}', headers=self.auth_admin)
                self.assertEqual(response.status_code, 422)

    def test_list_query_count_does_not_grow_with_rows(self):
        contact = services.create_contact_service(name='Landlord')
        for _ in range(3):
            self.create(account_id=self.account.pk, contact_id=contact.pk)

        with self.assertNumQueries(3):  # user lookup + count + page
            self.client.get('/api/transaction', headers=self.auth_member)

        for _ in range(20):
            self.create(account_id=self.account.pk, contact_id=contact.pk)

        with self.assertNumQueries(3):
            self.client.get('/api/transaction?ordering=-amount', headers=self.auth_member)

    # Get

    def test_get_transaction(self):
        response = self.client.get(f'/api/transaction/{self.tx.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], self.tx.pk)

    def test_get_transaction_from_not_linked_company_returns_404(self):
        response = self.client.get(f'/api/transaction/{self.other_tx.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 404)

    # Update

    def test_update_transaction_partial(self):
        response = self.patch(self.tx.pk, {'status': 'realized'})

        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'realized')
        self.assertEqual(self.tx.amount, Decimal('100.00'))

    def test_update_transaction_link_and_unlink_account(self):
        self.assertEqual(self.patch(self.tx.pk, {'account_id': self.account.pk}).status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.account, self.account)

        self.assertEqual(self.patch(self.tx.pk, {'account_id': None}).status_code, 200)
        self.tx.refresh_from_db()
        self.assertIsNone(self.tx.account)

    def test_update_transaction_null_on_required_field_returns_422(self):
        for field in ('amount', 'date', 'subgroup_id', 'type', 'status'):
            with self.subTest(field=field):
                self.assertEqual(self.patch(self.tx.pk, {field: None}).status_code, 422)

    def test_update_transaction_ignores_company_id(self):
        response = self.patch(self.tx.pk, {'company_id': self.other_company.pk, 'notes': 'x'}, self.auth_admin)

        self.assertEqual(response.status_code, 200)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.company, self.company)

    def test_update_transaction_from_not_linked_company_returns_404(self):
        response = self.patch(self.other_tx.pk, {'notes': 'hacked'})

        self.assertEqual(response.status_code, 404)
        self.other_tx.refresh_from_db()
        self.assertEqual(self.other_tx.notes, '')

    def test_update_transaction_with_account_from_another_company_returns_400(self):
        response = self.patch(self.tx.pk, {'account_id': self.other_account.pk})

        self.assertEqual(response.status_code, 400)

    # Delete

    def test_delete_transaction(self):
        response = self.client.delete(f'/api/transaction/{self.tx.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Transaction.objects.filter(pk=self.tx.pk).exists())

    def test_delete_transaction_from_not_linked_company_returns_404(self):
        response = self.client.delete(f'/api/transaction/{self.other_tx.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=self.other_tx.pk).exists())
