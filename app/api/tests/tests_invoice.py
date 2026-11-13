from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from ninja_jwt.tokens import AccessToken

from apps.attachments import services as attachment_services
from apps.attachments.models import Attachment
from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Group, Invoice, InvoiceEvent, InvoiceKind, TransactionType
from apps.users.models import Role, User

MEMORY_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


@override_settings(STORAGES=MEMORY_STORAGES)
class InvoiceEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='B', cnpj='11222333000181')
        for user in (self.finance, self.accountant, self.manager):
            user.companies.add(self.company)
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        self.contact = services.create_contact_service(name='Landlord')
        self.expense = self.tx(self.rent, TransactionType.OUTFLOW, contact_id=self.contact.pk)
        self.revenue = self.tx(self.sales, TransactionType.INFLOW, day=date(2026, 2, 5))
        self.other_expense = self.tx(self.rent, TransactionType.OUTFLOW, company=self.other_company)

    def tx(self, subgroup, type, company=None, day=date(2026, 1, 10), **extra):
        return services.create_transaction_service(
            user=self.admin, company_id=(company or self.company).pk, subgroup_id=subgroup.pk,
            date=day, amount=Decimal('100'), type=type, **extra,
        )

    def invoice(self, tx=None, **fields):
        return services.create_invoice_service(user=self.admin, transaction_id=(tx or self.expense).pk, **fields)

    def attach(self, invoice):
        with self.captureOnCommitCallbacks(execute=True):
            attachment_services.upload_attachment_service(
                user=self.admin, target='invoice', target_id=invoice.pk,
                file=SimpleUploadedFile('nf.pdf', b'%PDF', content_type='application/pdf'),
            )

    def post(self, data, user=None):
        return self.client.post('/api/invoice', data=data, content_type='application/json',
                                headers=auth_for(user or self.finance))

    def patch(self, invoice_id, data, user=None):
        return self.client.patch(f'/api/invoice/{invoice_id}', data=data, content_type='application/json',
                                 headers=auth_for(user or self.finance))

    def pending(self, query='', user=None):
        response = self.client.get(f'/api/invoice/pending?{query}', headers=auth_for(user or self.finance))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['items']

    # Create

    def test_require_invoice_for_expense(self):
        response = self.post({'transaction_id': self.expense.pk})

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['kind'], 'service')
        self.assertFalse(data['done'])
        self.assertEqual(data['direction'], 'receive')

    def test_revenue_requires_service_and_product_invoices(self):
        for kind in ('service', 'product'):
            response = self.post({'transaction_id': self.revenue.pk, 'kind': kind})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()['direction'], 'issue')

        self.assertEqual(self.revenue.invoices.count(), 2)

    def test_duplicate_kind_returns_400(self):
        self.post({'transaction_id': self.expense.pk, 'kind': 'service'})

        self.assertEqual(self.post({'transaction_id': self.expense.pk, 'kind': 'service'}).status_code, 400)

    def test_create_done_invoice_validation(self):
        cases = {
            'received without date': ({'transaction_id': self.expense.pk, 'done': True}, 400),
            'received with date': ({'transaction_id': self.expense.pk, 'done': True, 'issue_date': '2026-01-12'}, 201),
            'issued without number': ({'transaction_id': self.revenue.pk, 'done': True, 'issue_date': '2026-02-05'}, 400),
            'issued with number': ({'transaction_id': self.revenue.pk, 'done': True, 'issue_date': '2026-02-05',
                                    'number': ' 1234 '}, 201),
        }
        for name, (body, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.post(body).status_code, status)
        self.assertEqual(Invoice.objects.get(transaction=self.revenue).number, '1234')

    def test_create_for_not_linked_company_returns_404(self):
        self.assertEqual(self.post({'transaction_id': self.other_expense.pk}).status_code, 404)

    def test_create_without_change_permission_returns_403(self):
        self.assertEqual(self.post({'transaction_id': self.expense.pk}, user=self.accountant).status_code, 403)

    def test_create_invalid_kind_returns_422(self):
        self.assertEqual(self.post({'transaction_id': self.expense.pk, 'kind': 'banana'}).status_code, 422)

    # List / get

    def test_list_invoices_of_transaction(self):
        inv = self.invoice()
        self.invoice(tx=self.revenue)

        response = self.client.get(f'/api/invoice?transaction_id={self.expense.pk}', headers=auth_for(self.accountant))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([i['id'] for i in response.json()], [inv.pk])

    def test_get_invoice_scope(self):
        mine = self.invoice()
        other = self.invoice(tx=self.other_expense)

        self.assertEqual(self.client.get(f'/api/invoice/{mine.pk}', headers=auth_for(self.finance)).status_code, 200)
        self.assertEqual(self.client.get(f'/api/invoice/{other.pk}', headers=auth_for(self.finance)).status_code, 404)

    def test_manager_cannot_view_invoices(self):
        self.assertEqual(
            self.client.get(f'/api/invoice?transaction_id={self.expense.pk}', headers=auth_for(self.manager)).status_code,
            403,
        )

    # Update

    def test_mark_invoice_as_received(self):
        inv = self.invoice()

        response = self.patch(inv.pk, {'done': True, 'issue_date': '2026-01-12', 'number': '55'})

        self.assertEqual(response.status_code, 200)
        inv.refresh_from_db()
        self.assertTrue(inv.done)
        self.assertEqual(inv.issue_date, date(2026, 1, 12))

    def test_mark_done_without_date_returns_400(self):
        inv = self.invoice()

        self.assertEqual(self.patch(inv.pk, {'done': True}).status_code, 400)
        inv.refresh_from_db()
        self.assertFalse(inv.done)

    def test_clearing_date_of_done_invoice_returns_400(self):
        inv = self.invoice(done=True, issue_date=date(2026, 1, 12))

        self.assertEqual(self.patch(inv.pk, {'issue_date': None}).status_code, 400)

    def test_patch_null_on_required_returns_422(self):
        inv = self.invoice()

        self.assertEqual(self.patch(inv.pk, {'done': None}).status_code, 422)

    def test_update_other_company_returns_404(self):
        inv = self.invoice(tx=self.other_expense)

        self.assertEqual(self.patch(inv.pk, {'notes': 'x'}).status_code, 404)

    # Delete

    def test_delete_invoice_and_its_attachments(self):
        inv = self.invoice()
        self.attach(inv)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f'/api/invoice/{inv.pk}', headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(Attachment.objects.exists())

    def test_deleting_transaction_cascades_invoices_and_attachments(self):
        inv = self.invoice()
        self.attach(inv)

        with self.captureOnCommitCallbacks(execute=True):
            services.delete_transaction_service(user=self.admin, transaction_id=self.expense.pk)

        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(Attachment.objects.exists())

    # Attachments on invoices

    def test_attach_file_to_invoice_via_api(self):
        inv = self.invoice()

        response = self.client.post('/api/attachment', data={
            'target': 'invoice', 'target_id': inv.pk,
            'file': SimpleUploadedFile('nf.xml', b'<nfe/>', content_type='application/xml'),
        }, headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(inv.attachments.count(), 1)

    def test_attach_to_other_company_invoice_returns_404(self):
        inv = self.invoice(tx=self.other_expense)

        response = self.client.post('/api/attachment', data={
            'target': 'invoice', 'target_id': inv.pk, 'file': SimpleUploadedFile('nf.pdf', b'%PDF'),
        }, headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 404)

    # Pending report

    def test_pending_report(self):
        missing = self.invoice()                                                     # not received
        no_file = self.invoice(tx=self.revenue, kind=InvoiceKind.SERVICE, done=True,
                               issue_date=date(2026, 2, 5), number='1')              # issued, no file
        complete = self.invoice(tx=self.revenue, kind=InvoiceKind.PRODUCT, done=True,
                                issue_date=date(2026, 2, 5), number='2')
        self.attach(complete)                                                        # issued + file
        self.invoice(tx=self.other_expense)                                          # other company

        items = {i['id']: i for i in self.pending()}

        self.assertEqual(set(items), {missing.pk, no_file.pk})
        self.assertEqual(items[missing.pk]['pending_reason'], 'missing_invoice')
        self.assertEqual(items[missing.pk]['direction'], 'receive')
        self.assertEqual(items[missing.pk]['contact_name'], 'Landlord')
        self.assertEqual(items[missing.pk]['company_name'], 'A')
        self.assertEqual(items[missing.pk]['transaction_date'], '2026-01-10')
        self.assertEqual(Decimal(items[missing.pk]['transaction_amount']), Decimal('100'))
        self.assertEqual(items[no_file.pk]['pending_reason'], 'missing_attachment')
        self.assertEqual(items[no_file.pk]['direction'], 'issue')

    def test_not_done_with_file_is_still_pending(self):
        inv = self.invoice()
        self.attach(inv)

        self.assertEqual([i['id'] for i in self.pending()], [inv.pk])

    def test_pending_filters(self):
        to_receive = self.invoice()
        to_issue = self.invoice(tx=self.revenue, kind=InvoiceKind.PRODUCT)
        no_file = self.invoice(tx=self.revenue, kind=InvoiceKind.SERVICE, done=True,
                               issue_date=date(2026, 2, 5), number='1')
        cases = {
            'direction receive': ('direction=receive', [to_receive]),
            'direction issue': ('direction=issue', [to_issue, no_file]),
            'kind': ('kind=product', [to_issue]),
            'reason': ('reason=missing_attachment', [no_file]),
            'date range': ('date_from=2026-02-01&date_to=2026-02-28', [to_issue, no_file]),
            'company': (f'company_id={self.company.pk}', [to_receive, to_issue, no_file]),
        }
        for name, (query, expected) in cases.items():
            with self.subTest(filter=name):
                self.assertCountEqual([i['id'] for i in self.pending(query, user=self.admin)], [i.pk for i in expected])

    def test_pending_admin_sees_all_companies(self):
        self.invoice()
        other = self.invoice(tx=self.other_expense)

        self.assertIn(other.pk, [i['id'] for i in self.pending(user=self.admin)])
        self.assertNotIn(other.pk, [i['id'] for i in self.pending(user=self.finance)])

    def test_pending_invalid_filter_returns_422(self):
        response = self.client.get('/api/invoice/pending?direction=sideways', headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 422)

    def test_pending_query_count_constant(self):
        for _ in range(5):
            tx = self.tx(self.rent, TransactionType.OUTFLOW, contact_id=self.contact.pk)
            self.invoice(tx=tx)
        self.client.get('/api/invoice/pending', headers=auth_for(self.finance))  # warm ContentType cache

        with self.assertNumQueries(3):  # user + count + page
            self.client.get('/api/invoice/pending', headers=auth_for(self.finance))

    # History

    def test_history_records_user(self):
        inv = services.create_invoice_service(user=self.finance, transaction_id=self.expense.pk)
        services.update_invoice_service(user=self.finance, invoice_id=inv.pk, done=True, issue_date=date(2026, 1, 12))

        events = InvoiceEvent.objects.filter(pgh_obj_id=inv.pk).order_by('pgh_id')
        self.assertEqual([e.pgh_label for e in events], ['insert', 'update'])
        self.assertEqual({e.pgh_context.metadata['user'] for e in events}, {self.finance.pk})
