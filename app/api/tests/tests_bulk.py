from datetime import date
from decimal import Decimal

import pghistory.models
from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Account, Group, Transaction, TransactionStatus, TransactionType
from apps.sales.models import Sale
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class BulkTransactionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.member = User.objects.create_user(email='m@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.a = Company.objects.create(name='A', cnpj='81585365000127')
        self.b = Company.objects.create(name='B', cnpj='11222333000181')
        self.member.companies.add(self.a)
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.revenue = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        self.account = Account.objects.create(company=self.a, name='Itaú')
        self.t1 = self.create()
        self.t2 = self.create(date=date(2026, 1, 20))

    def create(self, company=None, **overrides):
        data = {
            'company_id': (company or self.a).pk, 'subgroup_id': self.rent.pk, 'account_id': self.account.pk,
            'date': date(2026, 1, 10), 'amount': Decimal('100.00'), 'type': TransactionType.OUTFLOW,
        }
        data.update(overrides)
        if company and company != self.a:
            data['account_id'] = None
        return services.create_transaction_service(user=self.admin, **data)

    def post(self, path, body, user=None):
        return self.client.post(f'/api/transaction/{path}', data=body, content_type='application/json',
                                headers=auth_for(user or self.admin))

    def ids(self, *txs):
        return [t.pk for t in (txs or (self.t1, self.t2))]

    def test_set_status_and_subgroup(self):
        r = self.post('bulk-update', {'ids': self.ids(), 'status': 'realized', 'subgroup_id': self.revenue.pk})
        self.assertEqual(r.json(), {'affected': 2})
        for t in Transaction.objects.all():
            self.assertEqual((t.status, t.subgroup_id), (TransactionStatus.REALIZED, self.revenue.pk))

    def test_shift_days_keeps_each_date(self):
        self.post('bulk-update', {'ids': self.ids(), 'shift_days': 31})
        self.t1.refresh_from_db(), self.t2.refresh_from_db()
        self.assertEqual((self.t1.date, self.t2.date), (date(2026, 2, 10), date(2026, 2, 20)))

    def test_change_company_drops_account(self):
        self.post('bulk-update', {'ids': self.ids(), 'company_id': self.b.pk})
        self.t1.refresh_from_db()
        self.assertEqual((self.t1.company_id, self.t1.account_id), (self.b.pk, None))

    def test_change_company_rejected_when_linked_to_sale(self):
        sale = Sale.objects.create(company=self.a, date=date(2026, 1, 1), amount=Decimal('200'))
        Transaction.objects.filter(pk=self.t1.pk).update(sale=sale)
        r = self.post('bulk-update', {'ids': self.ids(), 'company_id': self.b.pk})
        self.assertEqual(r.status_code, 400)

    def test_link_sale_only_inflows_of_same_company(self):
        sale = Sale.objects.create(company=self.a, date=date(2026, 1, 1), amount=Decimal('200'))
        self.assertEqual(self.post('bulk-update', {'ids': self.ids(), 'sale_id': sale.pk}).status_code, 400)
        inflow = self.create(type=TransactionType.INFLOW, subgroup_id=self.revenue.pk)
        self.assertEqual(self.post('bulk-update', {'ids': [inflow.pk], 'sale_id': sale.pk}).status_code, 200)
        self.assertEqual(sale.receivables.count(), 1)
        self.post('bulk-update', {'ids': [inflow.pk], 'sale_id': None})
        self.assertEqual(sale.receivables.count(), 0)

    def test_unlink_contact(self):
        r = self.post('bulk-update', {'ids': self.ids(), 'contact_id': None})
        self.assertEqual(r.status_code, 200)

    def test_validation(self):
        self.assertEqual(self.post('bulk-update', {'ids': self.ids()}).status_code, 422)
        self.assertEqual(self.post('bulk-update', {'ids': self.ids(), 'date': '2026-01-01', 'shift_days': 1}).status_code, 422)
        self.assertEqual(self.post('bulk-update', {'ids': self.ids(), 'status': None}).status_code, 422)
        self.assertEqual(self.post('bulk-update', {'ids': [], 'status': 'realized'}).status_code, 422)

    def test_other_company_is_not_found(self):
        other = self.create(company=self.b)
        r = self.post('bulk-update', {'ids': self.ids(self.t1, other), 'status': 'realized'}, user=self.member)
        self.assertEqual(r.status_code, 404)
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.status, TransactionStatus.PLANNED)

    def test_transfer_rejected(self):
        transfer = services.create_transfer_service(
            user=self.admin, from_company_id=self.a.pk, to_company_id=self.b.pk, date=date(2026, 1, 1), amount=Decimal('5'),
        )
        leg = transfer.transactions.first()
        self.assertEqual(self.post('bulk-delete', {'ids': [leg.pk]}).status_code, 400)

    def test_bulk_delete_logs_user(self):
        r = self.post('bulk-delete', {'ids': self.ids()})
        self.assertEqual(r.json(), {'affected': 2})
        self.assertFalse(Transaction.objects.filter(pk__in=self.ids()).exists())
        self.assertTrue(pghistory.models.Events.objects.filter(pgh_label='delete', pgh_context__user=self.admin.pk).exists())
