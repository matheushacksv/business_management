from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from ninja_jwt.tokens import AccessToken

from api.tests.tests_sales import MEMORY_STORAGES
from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Contact, Group, Invoice, Transaction, TransactionStatus
from apps.integrations.models import AsaasConfig, WebhookEvent
from apps.sales import services as sales
from apps.sales.models import Product
from apps.users.models import User


class FakeAsaas:
    """Stands in for asaas.request: records calls, answers like the API."""

    def __init__(self, cnpj):
        self.cnpj, self.calls, self.n = cnpj, [], 0

    def __call__(self, config, method, path, body=None, **query):
        self.calls.append((method, path, body, query))
        if path == '/myAccount/commercialInfo':
            return {'cpfCnpj': self.cnpj}
        if method == 'GET':
            return {'data': []}
        self.n += 1
        prefix = {'/customers': 'cus', '/payments': 'pay', '/invoices': 'inv'}.get(path, 'x')
        return {'id': f'{prefix}_{self.n}'}

    def made(self, method, path):
        return [c for c in self.calls if c[0] == method and c[1] == path]


@override_settings(STORAGES=MEMORY_STORAGES)
class AsaasTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.account = finance.create_account_service(user=self.admin, company_id=self.company.pk, name='Banco')
        self.subgroup = finance.create_subgroup_service(name='Assessorias', group=Group.OPERATING_REVENUE)
        self.contact = Contact.objects.create(name='Fulano', kind='customer', document='12345678000190', email='f@x.com',
                                              postal_code='90000000', address_number='10', address_district='Centro')
        self.sale = sales.create_sale_service(user=self.admin, company_id=self.company.pk, date=date(2026, 11, 1),
                                              amount=Decimal('3000'), contact_id=self.contact.pk,
                                              product_id=Product.objects.create(name='ASSESSORIAS').pk)
        sales.generate_receivables_service(user=self.admin, sale_id=self.sale.pk, subgroup_id=self.subgroup.pk,
                                           first_date=date(2026, 12, 10), installments=2, down_payment=Decimal('1000'),
                                           down_payment_date=date(2026, 11, 25))
        self.fake = FakeAsaas(self.company.cnpj)
        patcher = patch('apps.integrations.asaas.request', self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def auth(self):
        return {'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'}  # type:ignore

    def configure(self, **extra):
        body = {'api_key': 'k', 'sandbox': True, 'account_id': self.account.pk, 'fine_percent': '10',
                'interest_percent': '0', 'invoice_percent': '50', 'service_id': '490881', 'service_name': 'Mentoria',
                'iss_rate': '3', 'description_template': AsaasConfig._meta.get_field('description_template').default, **extra}
        return self.client.put(f'/api/integrations/asaas/{self.company.pk}', data=body, content_type='application/json',
                               headers=self.auth())

    def hook(self, payload, token=None):
        return self.client.post('/api/webhooks/asaas', data=payload, content_type='application/json',
                                headers={'asaas-access-token': token or AsaasConfig.objects.get().webhook_token})

    def test_key_of_another_account_is_rejected(self):
        self.fake.cnpj = '11111111000111'
        self.assertEqual(self.configure().status_code, 400)
        r = self.client.get('/api/integrations/asaas', headers=self.auth()).json()
        self.assertFalse(r[0]['has_key'])
        self.assertNotIn('api_key', r[0])

    def test_charges_then_payment_settles_and_issues_invoice(self):
        self.assertEqual(self.configure().status_code, 200)
        r = self.client.post(f'/api/sale/{self.sale.pk}/asaas-charges', headers=self.auth())
        self.assertEqual(r.json(), {'created': 3}, r.content)
        self.assertEqual(len(self.fake.made('POST', '/customers')), 1)
        self.assertEqual(len(self.fake.made('POST', '/payments')), 3)
        self.assertEqual(self.client.post(f'/api/sale/{self.sale.pk}/asaas-charges', headers=self.auth()).status_code, 400)

        down = Transaction.objects.get(reference='Entrada')
        self.assertEqual(self.hook({'event': 'PAYMENT_CREATED'}, token='wrong').status_code, 401)
        paid = {'event': 'PAYMENT_RECEIVED', 'payment': {'id': down.asaas_id, 'value': 1000, 'paymentDate': '2026-11-24'}}
        self.assertEqual(self.hook(paid).json()['status'], 'processed')
        down.refresh_from_db()
        self.assertEqual((down.status, down.date, down.account_id), ('realized', date(2026, 11, 24), self.account.pk))
        body = self.fake.made('POST', '/invoices')[0][2]
        self.assertEqual(body['value'], 500.0)
        self.assertEqual(body['municipalServiceId'], '490881')
        self.assertTrue(body['serviceDescription'].startswith('50% referente a entrada de ASSESSORIAS'), body)
        self.assertIn('01/11/2026', body['serviceDescription'])

        self.hook(paid)  # Asaas redelivery: no second NFS-e
        self.assertEqual(len(self.fake.made('POST', '/invoices')), 1)
        product = Invoice.objects.get(kind='product')
        self.assertEqual((product.transaction_id, product.done, product.asaas_id), (down.pk, False, ''))
        invoice = Invoice.objects.get(kind='service')
        authorized = {'event': 'INVOICE_AUTHORIZED', 'invoice': {
            'id': invoice.asaas_id, 'status': 'AUTHORIZED', 'number': '123', 'effectiveDate': '2026-11-24',
            'pdfUrl': 'https://sandbox.asaas.com/n/1.pdf', 'xmlUrl': 'https://evil.example/x.xml'}}
        with patch('urllib.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'%PDF-1'
            self.assertEqual(self.hook(authorized).json()['status'], 'processed')
            self.hook(authorized)  # redelivery: no second file
        invoice.refresh_from_db()
        self.assertEqual((invoice.done, invoice.number), (True, '123'))
        self.assertEqual(urlopen.call_count, 1)  # only the asaas.com link
        self.assertEqual([a.name for a in invoice.attachments.all()], ['NFS-e 123.pdf'])
        self.assertEqual(WebhookEvent.objects.filter(source='asaas').count(), 4)

    def test_settled_in_the_system_is_received_on_asaas(self):
        self.configure()
        self.client.post(f'/api/sale/{self.sale.pk}/asaas-charges', headers=self.auth())
        first, second = Transaction.objects.filter(sale=self.sale).exclude(asaas_id='').order_by('date')[:2]
        finance.update_transaction_service(user=self.admin, transaction_id=first.pk, status=TransactionStatus.REALIZED,
                                           date=date(2026, 11, 27))  # Pix straight to the account
        self.assertEqual(self.fake.made('POST', f'/payments/{first.asaas_id}/receiveInCash')[0][2],
                         {'paymentDate': '2026-11-27', 'value': float(first.amount), 'notifyCustomer': False})
        finance.bulk_update_transactions_service(user=self.admin, ids=[second.pk], status=TransactionStatus.REALIZED)
        self.assertEqual(len(self.fake.made('POST', f'/payments/{second.asaas_id}/receiveInCash')), 1)

    def test_partial_payment_splits_installment_and_rest_keeps_charge(self):
        self.configure()
        self.client.post(f'/api/sale/{self.sale.pk}/asaas-charges', headers=self.auth())
        tx = Transaction.objects.get(sale=self.sale, series_index=1)
        tx.reference = '1/2'
        tx.save()
        r = self.client.post(f'/api/transaction/{tx.pk}/split', data={'amount': '400', 'date': '2026-12-10', 'paid': True,
                             'rest_date': '2026-12-14'}, content_type='application/json', headers=self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        part, rest = r.json()
        self.assertEqual((part['reference'], part['amount'], part['status']), ('1/2a', '400.00', 'realized'))
        self.assertEqual(Transaction.objects.get(pk=part['id']).sale_id, self.sale.pk)
        self.assertEqual((rest['id'], rest['reference'], rest['date'], rest['status']), (tx.pk, '1/2b', '2026-12-14', 'planned'))
        self.assertEqual(self.fake.calls[-1][:3], ('POST', f'/payments/{tx.asaas_id}', {'dueDate': '2026-12-14', 'value': float(Decimal(rest['amount']))}))
        self.assertFalse([c for c in self.fake.calls if c[1].endswith('/receiveInCash')])  # the paid part had no charge

    def test_edits_and_deletes_follow_to_asaas(self):
        self.configure()
        self.client.post(f'/api/sale/{self.sale.pk}/asaas-charges', headers=self.auth())
        tx = Transaction.objects.filter(series__isnull=False).first()
        finance.update_transaction_service(user=self.admin, transaction_id=tx.pk, date=date(2026, 12, 15))
        self.assertEqual(self.fake.calls[-1][:3], ('POST', f'/payments/{tx.asaas_id}', {'dueDate': '2026-12-15', 'value': float(tx.amount)}))
        self.hook({'event': 'PAYMENT_UPDATED', 'payment': {'id': tx.asaas_id, 'dueDate': '2026-12-20', 'value': 1500}})
        tx.refresh_from_db()
        self.assertEqual((tx.date, tx.amount), (date(2026, 12, 20), Decimal('1500')))
        sales.delete_sale_service(user=self.admin, sale_id=self.sale.pk)
        self.assertEqual(len(self.fake.made('DELETE', f'/payments/{tx.asaas_id}')), 1)
        self.assertEqual(len([c for c in self.fake.calls if c[0] == 'DELETE']), 3)
