import hashlib
import hmac
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Contact, Group, Invoice, InvoiceKind, Transaction
from apps.integrations import bling
from apps.integrations.models import BlingConfig, WebhookEvent
from apps.sales import services as sales
from apps.users.models import User

ADDRESS = {'endereco': 'Rua A', 'numero': '10', 'complemento': '', 'bairro': 'Centro', 'cep': '90000000',
           'municipio': 'Porto Alegre', 'uf': 'RS'}


class FakeBling:
    """Stands in for bling.request: one NF-e (id 99) whose `situacao` the test sets."""

    def __init__(self):
        self.calls, self.status = [], 5

    def __call__(self, company_id, method, path, body=None, **query):
        self.calls.append((method, path, body))
        if path == '/nfe' and method == 'POST':
            return {'data': {'id': 99, 'numero': '000123', 'serie': '1'}}
        if path == '/nfe/99' and method == 'GET':
            return {'data': {'id': 99, 'situacao': self.status, 'numero': '000123', 'dataEmissao': '2026-11-25 10:00:00',
                             'linkPDF': 'https://www.bling.com.br/doc.pdf', 'xml': 'https://www.bling.com.br/doc.xml'}}
        if path == '/naturezas-operacoes':
            return {'data': [{'id': 7, 'descricao': 'Venda de mercadoria', 'situacao': 1}]}
        return {'data': {}}

    def made(self, method, path):
        return [c for c in self.calls if c[0] == method and c[1] == path]


class BlingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        subgroup = finance.create_subgroup_service(name='Assessorias', group=Group.OPERATING_REVENUE)
        contact = Contact.objects.create(name='Fulano', kind='customer', document='12345678000190', email='f@x.com',
                                         postal_code='90000000', address_number='10', address_district='Centro')
        self.plan = sales.create_plan_service(name='Starter', nfe_skus=['AP01', ' AP02 ', 'AP03', 'AP04', ''])
        sale = sales.create_sale_service(user=self.admin, company_id=self.company.pk, date=date(2026, 11, 1),
                                         amount=Decimal('20000'), contact_id=contact.pk, plan_id=self.plan.pk)
        sales.generate_receivables_service(user=self.admin, sale_id=sale.pk, subgroup_id=subgroup.pk,
                                           first_date=date(2026, 12, 10), installments=10)
        self.tx = Transaction.objects.filter(sale=sale).first()
        self.invoice = Invoice.objects.create(transaction=self.tx, kind=InvoiceKind.PRODUCT)
        self.config = BlingConfig.objects.create(company=self.company, client_id='cid', client_secret='secret', nature_id=7,
                                                 access_token='at', refresh_token='rt',
                                                 expires_at=timezone.now() + timedelta(hours=6))
        self.fake = FakeBling()
        for target, value in (('request', self.fake), ('_address', lambda c: ADDRESS), ('attach_files', lambda *a: [])):
            patcher = patch(f'apps.integrations.bling.{target}', value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def auth(self):
        return {'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'}  # type:ignore

    def test_split_keeps_total(self):
        self.assertEqual(bling.split(Decimal('1000'), 3), [Decimal('333.33'), Decimal('333.33'), Decimal('333.34')])
        self.assertEqual(self.plan.nfe_skus, ['AP01', 'AP02', 'AP03', 'AP04'])

    def test_issue_splits_half_of_installment_among_handouts(self):
        r = self.client.post(f'/api/invoice/{self.invoice.pk}/bling', headers=self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        body = self.fake.made('POST', '/nfe')[0][2]
        self.assertEqual(self.tx.amount, Decimal('2000'))  # 10x 2.000 (the client's example)
        self.assertEqual([(i['codigo'], i['valor']) for i in body['itens']], [('AP01', 250.0), ('AP02', 250.0), ('AP03', 250.0), ('AP04', 250.0)])
        self.assertEqual((body['naturezaOperacao']['id'], body['contato']['tipoPessoa']), (7, 'J'))
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.done, self.invoice.number, self.invoice.bling_id), (True, '000123', '99'))
        self.assertFalse(self.fake.made('POST', '/nfe/99/enviar'))  # already authorized: not sent again

    def test_rejected_then_retry_reuses_the_nfe(self):
        self.fake.status = 4
        bling.issue_service(invoice_id=self.invoice.pk)
        self.invoice.refresh_from_db()
        self.assertFalse(self.invoice.done)
        self.assertIn('rejeitada', self.invoice.notes)
        self.fake.status = 5  # fixed in Bling, sent again from the system
        bling.issue_service(invoice_id=self.invoice.pk)
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.done)
        self.assertEqual(len(self.fake.made('POST', '/nfe')), 1)
        self.assertEqual(len(self.fake.made('POST', '/nfe/99/enviar')), 1)  # authorized by then: not sent again

    def test_payment_without_plan_items_leaves_reason(self):
        self.plan.nfe_skus = []
        self.plan.save()
        bling.issue_on_payment(self.invoice)  # never raises (called from the Asaas webhook)
        self.invoice.refresh_from_db()
        self.assertFalse(self.invoice.done)
        self.assertIn('sem itens de NF-e', self.invoice.notes)
        self.assertFalse(self.fake.made('POST', '/nfe'))

    def test_realized_by_hand_issues_product_nfe(self):
        self.invoice.delete()
        tx = Transaction.objects.filter(sale=self.tx.sale).exclude(pk=self.tx.pk).first()
        r = self.client.patch(f'/api/transaction/{tx.pk}', data={'status': 'realized'}, content_type='application/json', headers=self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Invoice.objects.get(transaction=tx, kind=InvoiceKind.PRODUCT).done)
        self.assertEqual(len(self.fake.made('POST', '/nfe')), 1)
        self.client.patch(f'/api/transaction/{tx.pk}', data={'notes': 'x'}, content_type='application/json', headers=self.auth())
        self.assertEqual(len(self.fake.made('POST', '/nfe')), 1)  # only on the planned -> realized change

    def test_webhook_signed_updates_invoice(self):
        self.fake.status = 1
        bling.issue_service(invoice_id=self.invoice.pk)
        self.fake.status = 5
        body = json.dumps({'event': 'invoice.updated', 'data': {'id': 99}}).encode()
        sig = 'sha256=' + hmac.new(b'secret', body, hashlib.sha256).hexdigest()
        url = f'/api/webhooks/bling/{self.company.pk}'
        self.assertEqual(self.client.get(url).status_code, 200)  # Bling probes the URL
        bad = self.client.post(url, data=body, content_type='application/json', headers={'X-Bling-Signature-256': 'sha256=x'})
        self.assertEqual(bad.status_code, 401)
        r = self.client.post(url, data=body, content_type='application/json', headers={'X-Bling-Signature-256': sig})
        self.assertEqual(r.json()['status'], 'processed')
        self.invoice.refresh_from_db()
        self.assertTrue(self.invoice.done)
        self.assertEqual(WebhookEvent.objects.get().source, 'bling')

    def test_oauth_callback_and_settings(self):
        r = self.client.post(f'/api/integrations/bling/{self.company.pk}/authorize', headers=self.auth())
        self.assertIn('client_id=cid', r.json()['url'])
        state = BlingConfig.objects.get().state
        tokens = {'access_token': 'new-at', 'refresh_token': 'new-rt', 'expires_in': 21600}
        with patch('apps.integrations.bling._call', return_value=tokens) as call:
            r = self.client.get(f'/api/integrations/bling/callback?code=abc&state={state}')
        self.assertEqual(r.status_code, 302)
        self.assertIn('bling=ok', r['Location'])
        self.assertIn(b'code=abc', call.call_args[0][0].data)
        self.assertEqual(BlingConfig.objects.get().refresh_token, 'new-rt')
        r = self.client.get('/api/integrations/bling/callback?code=abc&state=reused')
        self.assertNotIn('bling=ok', r['Location'])
        listed = self.client.get('/api/integrations/bling', headers=self.auth()).json()
        self.assertNotIn('client_secret', listed[0])
        self.assertTrue(listed[0]['connected'])
        self.assertEqual(self.client.get(f'/api/integrations/bling/{self.company.pk}/natures', headers=self.auth()).json(),
                         [{'id': 7, 'name': 'Venda de mercadoria'}])

    def test_expired_refresh_asks_to_authorize_again(self):
        self.config.expires_at = timezone.now() - timedelta(minutes=5)
        self.config.save()
        with patch('apps.integrations.bling._call', side_effect=ValidationError('Bling: invalid_grant')):
            with self.assertRaisesMessage(ValidationError, 'Autorizar no Bling'):
                bling._access_token(self.company.pk)
