from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Contact, Group, Transaction, TransactionStatus, TransactionType
from apps.sales.models import Commission, Sale, Salesperson, SaleStatus, StatementShare
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127', tax_rate=Decimal('10'))
        self.subgroup = finance.create_subgroup_service(name='Comissões sobre Vendas', group=Group.VARIABLE_COSTS)
        self.matheus = Salesperson.objects.create(name='Matheus')
        self.amanda = Salesperson.objects.create(name='Amanda')
        self.wagner = Salesperson.objects.create(name='Wagner')
        self.sale = Sale.objects.create(company=self.company, date=date(2026, 10, 15), amount=Decimal('20000'))

    def api(self, method, path, body=None, user=None):
        return getattr(self.client, method)(f'/api{path}', data=body, content_type='application/json',
                                            headers=auth_for(user or self.admin))

    def add(self, person, kind, **values):
        r = self.api('post', f'/sale/{self.sale.pk}/commissions', {'salesperson_id': person.pk, 'kind': kind, **values})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()


class CommissionTests(Base):
    def test_amounts_split_between_people(self):
        self.assertEqual(Decimal(self.add(self.matheus, 'advisor', percent='5')['amount']), Decimal('900.00'))  # 5% of 18.000
        self.assertEqual(Decimal(self.add(self.amanda, 'advisor', percent='5')['amount']), Decimal('900.00'))
        self.assertEqual(Decimal(self.add(self.matheus, 'crm', fixed_amount='500')['amount']), Decimal('500'))
        self.assertEqual(Decimal(self.add(self.wagner, 'crm', fixed_amount='250')['amount']), Decimal('250'))

    def test_kind_decides_percent_or_fixed(self):
        r = self.api('post', f'/sale/{self.sale.pk}/commissions', {'salesperson_id': self.matheus.pk, 'kind': 'seller', 'fixed_amount': '100'})
        self.assertEqual(r.status_code, 400)
        r = self.api('post', f'/sale/{self.sale.pk}/commissions', {'salesperson_id': self.matheus.pk, 'kind': 'crm', 'percent': '10'})
        self.assertEqual(r.status_code, 400)

    def test_due_the_month_after_the_sale(self):
        self.add(self.matheus, 'seller', percent='10')
        Sale.objects.create(company=self.company, date=date(2026, 11, 2), amount=Decimal('100'))
        self.assertEqual(len(self.api('get', '/commission?month=2026-11-01').json()), 1)
        self.assertEqual(len(self.api('get', '/commission?month=2026-10-01').json()), 0)

    def test_canceled_sale_drops_unpaid(self):
        self.add(self.matheus, 'seller', percent='10')
        Sale.objects.filter(pk=self.sale.pk).update(status=SaleStatus.CANCELED)
        self.assertEqual(self.api('get', '/commission').json(), [])

    def test_pay_groups_by_person_and_freezes(self):
        a = self.add(self.matheus, 'advisor', percent='5')
        b = self.add(self.matheus, 'crm', fixed_amount='500')
        c = self.add(self.amanda, 'advisor', percent='5')
        r = self.api('post', '/commission/pay', {'ids': [a['id'], b['id'], c['id']], 'date': '2026-11-10', 'subgroup_id': self.subgroup.pk})
        self.assertEqual(r.status_code, 200, r.content)
        totals = sorted(Decimal(t['amount']) for t in r.json())
        self.assertEqual(totals, [Decimal('900.00'), Decimal('1400.00')])
        tx = Transaction.objects.get(contact__name='Matheus')
        self.assertEqual((tx.type, tx.status, tx.subgroup_id), (TransactionType.OUTFLOW, TransactionStatus.REALIZED, self.subgroup.pk))
        # frozen: changing the tax or the sale keeps the paid amount; editing is blocked
        Company.objects.filter(pk=self.company.pk).update(tax_rate=Decimal('20'))
        self.assertEqual(Decimal(self.api('get', '/commission?status=paid').json()[0]['amount']), Decimal('900.00'))
        self.assertEqual(self.api('patch', f'/commission/{a["id"]}', {'percent': '1'}).status_code, 400)
        # paying again is refused; deleting the payment reopens it
        self.assertEqual(self.api('post', '/commission/pay', {'ids': [a['id']], 'date': '2026-11-10', 'subgroup_id': self.subgroup.pk}).status_code, 400)
        tx.delete()
        self.assertIsNone(Commission.objects.get(pk=a['id']).payment_id)

    def test_pay_reuses_existing_contact(self):
        Contact.objects.create(name='matheus')
        a = self.add(self.matheus, 'seller', percent='10')
        self.api('post', '/commission/pay', {'ids': [a['id']], 'date': '2026-11-10', 'subgroup_id': self.subgroup.pk})
        self.assertEqual(Contact.objects.filter(name__iexact='matheus').count(), 1)

    def test_other_company_is_hidden(self):
        member = User.objects.create_user(email='m@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.add(self.matheus, 'seller', percent='10')
        self.assertEqual(self.api('get', '/commission', user=member).json(), [])

    def test_export(self):
        self.add(self.matheus, 'seller', percent='10')
        r = self.api('get', '/commission/export')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'PK'))


class SalaryStatementTests(Base):
    def pay_salary(self, **extra):
        body = {'salesperson_id': self.matheus.pk, 'month': '2026-11-01', 'date': '2026-11-05',
                'company_id': self.company.pk, 'subgroup_id': self.subgroup.pk, **extra}
        return self.api('post', '/salary/pay', body)

    def test_statement_and_salary_frozen(self):
        Salesperson.objects.filter(pk=self.matheus.pk).update(monthly_salary=Decimal('3000'))
        self.add(self.matheus, 'seller', percent='10')
        st = self.api('get', f'/commission/statement?salesperson_id={self.matheus.pk}&month=2026-11-15').json()
        self.assertEqual((Decimal(st['salary']), st['salary_payment_id'], len(st['commissions'])), (Decimal('3000'), None, 1))
        r = self.pay_salary()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['reference'], 'Fixo ref. 10/2026')
        self.assertEqual(self.pay_salary().status_code, 400)  # once per month
        # raise: the paid month keeps 3000, the next one shows the new value
        Salesperson.objects.filter(pk=self.matheus.pk).update(monthly_salary=Decimal('3500'))
        st = self.api('get', f'/commission/statement?salesperson_id={self.matheus.pk}&month=2026-11-01').json()
        self.assertEqual((Decimal(st['salary']), st['salary_paid_on']), (Decimal('3000'), '2026-11-05'))
        nxt = self.api('get', f'/commission/statement?salesperson_id={self.matheus.pk}&month=2026-12-01').json()
        self.assertEqual(Decimal(nxt['salary']), Decimal('3500'))
        # deleting the outflow reopens the month
        Transaction.objects.get(pk=r.json()['id']).delete()
        st = self.api('get', f'/commission/statement?salesperson_id={self.matheus.pk}&month=2026-11-01').json()
        self.assertEqual((Decimal(st['salary']), st['salary_payment_id']), (Decimal('3500'), None))

    def test_no_salary_refused(self):
        self.assertEqual(self.pay_salary().status_code, 400)
        self.assertEqual(self.pay_salary(amount='1200').status_code, 200)


class StatementShareTests(Base):
    def setUp(self):
        super().setUp()
        self.add(self.matheus, 'seller', percent='10')
        r = self.api('post', '/commission/statement/share', {'salesperson_id': self.matheus.pk, 'month': '2026-11-01'})
        self.assertEqual(r.status_code, 200, r.content)
        self.share = r.json()

    def open(self, password, token=None):
        return self.client.post(f'/api/public/statement/{token or self.share["token"]}', data={'password': password},
                                content_type='application/json')

    def test_opens_without_login_with_password(self):
        r = self.open(self.share['password'].lower())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.json()['commissions']), 1)
        self.assertNotIn(self.share['password'], str(StatementShare.objects.get().password))  # stored hashed
        self.assertEqual(self.open('WRONG123').status_code, 400)
        self.assertEqual(self.open(self.share['password'], token='nope').status_code, 404)

    def test_locks_after_attempts_and_regenerating_invalidates(self):
        for _ in range(10):
            self.open('WRONG123')
        self.assertEqual(self.open(self.share['password']).status_code, 404)
        new = self.api('post', '/commission/statement/share', {'salesperson_id': self.matheus.pk, 'month': '2026-11-01'}).json()
        self.assertEqual(self.open(new['password'], token=new['token']).status_code, 200)
        self.assertEqual(self.open(self.share['password']).status_code, 404)
