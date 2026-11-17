from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Contact, Group, InvoiceKind, TransactionStatus, TransactionType
from apps.sales.models import Sale, SaleStatus
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class ContactPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.a = Company.objects.create(name='A', cnpj='81585365000127')
        self.b = Company.objects.create(name='B', cnpj='11222333000181')
        self.contact = Contact.objects.create(name='Maria')
        today = timezone.localdate()
        revenue = services.create_subgroup_service(name='Mentoria', group=Group.OPERATING_REVENUE)
        cost = services.create_subgroup_service(name='Plataforma', group=Group.VARIABLE_COSTS)

        def tx(company, subgroup, amount, type_, status, days):
            return services.create_transaction_service(
                user=self.admin, company_id=company.pk, subgroup_id=subgroup.pk, contact_id=self.contact.pk,
                date=today + timedelta(days=days), amount=Decimal(amount), type=type_, status=status,
            )

        self.received = tx(self.a, revenue, '1000', TransactionType.INFLOW, TransactionStatus.REALIZED, -30)
        tx(self.a, revenue, '500', TransactionType.INFLOW, TransactionStatus.PLANNED, 10)   # to receive
        tx(self.a, revenue, '300', TransactionType.INFLOW, TransactionStatus.PLANNED, -5)   # overdue
        tx(self.a, revenue, '200', TransactionType.INFLOW, TransactionStatus.PLANNED, -1)   # overdue
        tx(self.a, cost, '80', TransactionType.OUTFLOW, TransactionStatus.REALIZED, -3)     # paid (as supplier)
        tx(self.b, revenue, '9999', TransactionType.INFLOW, TransactionStatus.REALIZED, -2)  # other company
        services.create_invoice_service(user=self.admin, transaction_id=self.received.pk, kind=InvoiceKind.SERVICE)

        Sale.objects.create(company=self.a, contact=self.contact, date=today, amount=Decimal('3000'))
        Sale.objects.create(company=self.a, contact=self.contact, date=today, amount=Decimal('700'),
                            status=SaleStatus.CANCELED)
        Sale.objects.create(company=self.b, contact=self.contact, date=today, amount=Decimal('5000'))

    def summary(self, user):
        response = self.client.get(f'/api/contact/{self.contact.pk}/summary', headers=auth_for(user))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_summary_only_counts_the_users_companies(self):
        finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        finance.companies.add(self.a)
        data = self.summary(finance)
        self.assertEqual(Decimal(data['sales']['sold']), Decimal('3000'))  # canceled + company B left out
        self.assertEqual(data['sales']['sales_count'], 1)
        money = {k: (Decimal(v) if isinstance(v, str) else v) for k, v in data['money'].items()}
        self.assertEqual(money['received'], Decimal('1000'))
        self.assertEqual(money['to_receive'], Decimal('500'))
        self.assertEqual(money['overdue_receivable'], Decimal('500'))
        self.assertEqual(money['overdue_receivable_count'], 2)
        self.assertEqual(money['paid'], Decimal('80'))
        self.assertEqual(money['to_pay'], Decimal('0'))
        self.assertEqual(money['pending_invoices'], 1)

    def test_admin_sees_every_company(self):
        data = self.summary(self.admin)
        self.assertEqual(Decimal(data['sales']['sold']), Decimal('8000'))
        self.assertEqual(Decimal(data['money']['received']), Decimal('10999'))

    def test_blocks_follow_the_role(self):
        legal = User.objects.create_user(email='legal@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        legal.companies.add(self.a)
        data = self.summary(legal)  # legal sees contacts and sales, not transactions
        self.assertIsNotNone(data['sales'])
        self.assertIsNone(data['money'])
        manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        response = self.client.get(f'/api/contact/{self.contact.pk}/summary', headers=auth_for(manager))
        self.assertEqual(response.status_code, 403)  # no contacts module

    def test_missing_contact_is_404(self):
        response = self.client.get('/api/contact/999999/summary', headers=auth_for(self.admin))
        self.assertEqual(response.status_code, 404)

    def test_notes_and_pending_invoices_filter(self):
        response = self.client.patch(f'/api/contact/{self.contact.pk}', data={'notes': ' Prefere boleto. '},
                                     content_type='application/json', headers=auth_for(self.admin))
        self.assertEqual(response.json()['notes'], 'Prefere boleto.')
        other = Contact.objects.create(name='João')
        mine = self.client.get(f'/api/invoice/pending?contact_id={self.contact.pk}', headers=auth_for(self.admin))
        theirs = self.client.get(f'/api/invoice/pending?contact_id={other.pk}', headers=auth_for(self.admin))
        self.assertEqual(mine.json()['count'], 1)
        self.assertEqual(theirs.json()['count'], 0)
