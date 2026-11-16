from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import selectors, services
from apps.finance.models import Account, Group, SubGroup, Transaction, TransactionType, Transfer
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class TransferTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.member = User.objects.create_user(
            email='member@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE
        )
        self.a = Company.objects.create(name='Company A', cnpj='81585365000127', initial_balance=Decimal('1000'))
        self.b = Company.objects.create(name='Company B', cnpj='11222333000181')
        self.member.companies.add(self.a)  # sees only one side
        self.account_a = Account.objects.create(company=self.a, name='Itaú')
        self.account_b = Account.objects.create(company=self.b, name='Bradesco')
        self.auth = auth_for(self.admin)

    def body(self, **overrides):
        data = {
            'from_company_id': self.a.pk, 'to_company_id': self.b.pk, 'date': '2026-03-10',
            'amount': '250.00', 'status': 'realized',
            'from_account_id': self.account_a.pk, 'to_account_id': self.account_b.pk,
        }
        data.update(overrides)
        return data

    def post(self, data, auth=None):
        return self.client.post('/api/transfer', data=data, content_type='application/json', headers=auth or self.auth)

    def test_create_makes_two_linked_legs(self):
        response = self.post(self.body())
        self.assertEqual(response.status_code, 201, response.json())
        out = response.json()
        outflow = Transaction.objects.get(pk=out['outflow_id'])
        inflow = Transaction.objects.get(pk=out['inflow_id'])
        self.assertEqual((outflow.company, outflow.type, outflow.account), (self.a, 'outflow', self.account_a))
        self.assertEqual((inflow.company, inflow.type, inflow.account), (self.b, 'inflow', self.account_b))
        self.assertEqual(outflow.transfer_id, inflow.transfer_id)
        self.assertEqual(outflow.subgroup.group, Group.TRANSFER)
        self.assertFalse(outflow.is_reversal)
        self.assertEqual(out['from_company_name'], 'Company A')

    def test_validation(self):
        self.assertEqual(self.post(self.body(to_company_id=self.a.pk, to_account_id=None)).status_code, 400)
        self.assertEqual(self.post(self.body(to_account_id=self.account_a.pk)).status_code, 400)  # wrong company
        self.assertEqual(self.post(self.body(amount='0')).status_code, 422)

    def test_needs_access_to_both_companies(self):
        response = self.post(self.body(), auth=auth_for(self.member))
        self.assertEqual(response.status_code, 404)
        transfer_id = self.post(self.body()).json()['id']
        self.assertEqual(self.client.get(f'/api/transfer/{transfer_id}', headers=auth_for(self.member)).status_code, 404)

    def test_update_and_delete_change_both_legs(self):
        out = self.post(self.body(status='planned')).json()
        response = self.client.patch(
            f"/api/transfer/{out['id']}", data={'amount': '300.00', 'status': 'realized', 'to_account_id': None},
            content_type='application/json', headers=self.auth,
        )
        self.assertEqual(response.status_code, 200, response.json())
        legs = Transaction.objects.filter(transfer_id=out['id'])
        self.assertEqual({(t.amount, t.status) for t in legs}, {(Decimal('300.00'), 'realized')})
        self.assertIsNone(legs.get(type='inflow').account_id)
        self.assertEqual(legs.get(type='outflow').account_id, self.account_a.pk)

        self.assertEqual(self.client.delete(f"/api/transfer/{out['id']}", headers=self.auth).status_code, 204)
        self.assertFalse(Transaction.objects.filter(pk__in=[out['outflow_id'], out['inflow_id']]).exists())
        self.assertFalse(Transfer.objects.exists())

    def test_leg_cannot_change_alone(self):
        out = self.post(self.body()).json()
        tx = out['outflow_id']
        patch = self.client.patch(f'/api/transaction/{tx}', data={'amount': '1.00'},
                                  content_type='application/json', headers=self.auth)
        self.assertEqual(patch.status_code, 400)
        self.assertEqual(self.client.delete(f'/api/transaction/{tx}', headers=self.auth).status_code, 400)

    def test_transfer_group_is_reserved(self):
        self.post(self.body())
        subgroup = SubGroup.objects.get(group=Group.TRANSFER)
        tx = {'company_id': self.a.pk, 'subgroup_id': subgroup.pk, 'date': '2026-03-10',
              'amount': '10.00', 'type': 'outflow'}
        self.assertEqual(self.client.post('/api/transaction', data=tx, content_type='application/json',
                                          headers=self.auth).status_code, 400)
        sub = {'name': 'Outra', 'group': 'transfer'}
        self.assertEqual(self.client.post('/api/subgroup', data=sub, content_type='application/json',
                                          headers=self.auth).status_code, 400)
        self.assertEqual(self.client.patch(f'/api/subgroup/{subgroup.pk}', data={'name': 'X'},
                                           content_type='application/json', headers=self.auth).status_code, 400)

    def test_cash_flow_moves_money_and_dre_ignores_it(self):
        self.post(self.body())
        kwargs = {'user': self.admin, 'start': date(2026, 3, 1), 'end': date(2026, 3, 31)}
        only_a = selectors.cash_flow_selector(**kwargs, company_id=[self.a.pk])
        only_b = selectors.cash_flow_selector(**kwargs, company_id=[self.b.pk])
        both = selectors.cash_flow_selector(**kwargs)
        self.assertEqual(only_a['closing'], Decimal('750.00'))
        self.assertEqual(only_b['closing'], Decimal('250.00'))
        self.assertEqual(both['closing'], Decimal('1000.00'))  # consolidated: nets to zero

        dre = selectors.dre_selector(user=self.admin, year=2026)
        net = next(line for line in dre['lines'] if line['key'] == 'net_result')
        self.assertEqual(sum(net['months']), Decimal('0'))
        self.assertFalse(any('transfer' in line['key'] for line in dre['lines']))
        self.assertEqual(services.list_transactions_service(user=self.admin, type=TransactionType.INFLOW).count(), 1)
