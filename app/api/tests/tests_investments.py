from datetime import date
from decimal import Decimal

from django.test import TestCase

from api.tests.tests_attachment import auth_for
from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Group, Transaction
from apps.finance.selectors import dre_selector
from apps.users.models import Role, User


class InvestmentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other = Company.objects.create(name='B', cnpj='11222333000181')
        self.account = finance.create_account_service(user=self.admin, company_id=self.company.pk, name='Banco')

    def api(self, method, path, body=None, user=None):
        return getattr(self.client, method)(f'/api{path}', data=body, content_type='application/json',
                                            headers=auth_for(user or self.admin))

    def create(self, **extra):
        r = self.api('post', '/investment', {'company_id': self.company.pk, 'institution': 'XP', 'kind': 'cdb', **extra})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def move(self, inv, kind, amount, day, **extra):
        return self.api('post', f'/investment/{inv["id"]}/movements',
                        {'date': day, 'kind': kind, 'amount': amount, **extra})

    def test_position_and_cash_legs_out_of_dre(self):
        inv = self.create()
        self.assertEqual(self.move(inv, 'application', '10000', '2026-01-10', account_id=self.account.pk).status_code, 201)
        self.move(inv, 'balance', '10300', '2026-06-30')
        self.move(inv, 'redemption', '3000', '2026-07-05', account_id=self.account.pk)
        self.assertEqual(self.move(inv, 'redemption', '99999', '2026-07-06').status_code, 400)
        got = self.api('get', f'/investment/{inv["id"]}').json()
        self.assertEqual((Decimal(got['balance']), Decimal(got['yield_amount']), Decimal(got['yield_percent'])),
                         (Decimal('7300'), Decimal('300'), Decimal('4.29')))
        legs = Transaction.objects.order_by('date')
        self.assertEqual([(t.type, t.amount, t.subgroup.group) for t in legs],
                         [('outflow', Decimal('10000'), Group.TRANSFER), ('inflow', Decimal('3000'), Group.TRANSFER)])
        dre = dre_selector(user=self.admin, year=2026)
        self.assertTrue(all(sum(Decimal(v) for v in line['months']) == 0 for line in dre['lines']))
        # the leg is changed through the investment only
        self.assertEqual(self.api('delete', f'/transaction/{legs[0].pk}').status_code, 400)
        movement = self.api('get', f'/investment/{inv["id"]}/movements').json()[-1]
        self.assertEqual(self.api('delete', f'/investment-movement/{movement["id"]}').status_code, 204)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.api('delete', f'/investment/{inv["id"]}').status_code, 400)  # still has movements

    def test_personal_has_no_cash_leg_and_filters(self):
        inv = self.create(holder='personal', institution='Nubank')
        self.assertEqual(self.move(inv, 'application', '500', '2026-02-01', account_id=self.account.pk).status_code, 400)
        self.assertEqual(self.move(inv, 'application', '500', '2026-02-01').status_code, 201)
        self.assertEqual(Transaction.objects.count(), 0)
        self.create()
        self.assertEqual([i['institution'] for i in self.api('get', '/investment?holder=personal').json()], ['Nubank'])
        self.assertEqual(len(self.api('get', '/investment?as_of=2026-01-01').json()), 2)
        self.assertEqual(Decimal(self.api('get', '/investment?holder=personal&as_of=2026-01-01').json()[0]['balance']), 0)

    def test_scoped_by_company_and_role(self):
        self.create()
        legal = User.objects.create_user(email='j@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        self.assertEqual(self.api('get', '/investment', user=legal).status_code, 403)
        manager = User.objects.create_user(email='g@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        manager.companies.add(self.other)
        self.assertEqual(self.api('get', '/investment', user=manager).json(), [])
        self.assertEqual(self.api('post', '/investment', {'company_id': self.other.pk, 'institution': 'X'}, user=manager).status_code, 403)

    def test_export(self):
        self.create()
        r = self.api('get', '/investment/export')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'PK'))
