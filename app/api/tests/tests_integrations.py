import base64
from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Contact, Group, Transaction
from apps.integrations.models import PipedriveConfig, WebhookEvent
from apps.sales.models import Commission, Product, Sale, Salesperson
from apps.users.models import Role, User

DEAL = {
    'deal_id': 1234, 'person_id': 567, 'person_name': 'Fulano da Silva', 'person_email': 'Fulano@Empresa.com',
    'person_phone': '51999990000', 'client_document': '12.345.678/0001-90', 'company_document': '81.585.365/0001-27',
    'proposal_value': 'R$ 28.996,98', 'product': 'ASSESSORIAS', 'owner_name': 'renato luciano', 'installments': '10',
    'payment_method': 'PARCELADO NO ASAAS', 'notes': 'Obs', 'signed_date': '19/11/2026',
}


class PipedriveWebhookTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.renato = Salesperson.objects.create(name='Renato Luciano')
        self.subgroup = finance.create_subgroup_service(name='Assessorias', group=Group.OPERATING_REVENUE)
        r = self.client.post('/api/integrations/pipedrive/credentials', headers=self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        creds = r.json()
        self.basic = 'Basic ' + base64.b64encode(f'{creds["username"]}:{creds["password"]}'.encode()).decode()

    def auth(self, user=None):
        return {'Authorization': f'Bearer {AccessToken.for_user(user or self.admin)}'}  # type:ignore

    def post(self, body, auth=None):
        return self.client.post('/api/webhooks/pipedrive/deal', data=body, content_type='application/json',
                                headers={'Authorization': auth or self.basic})

    def test_rejects_without_credentials(self):
        self.assertEqual(self.post(DEAL, auth='Basic ' + base64.b64encode(b'x:y').decode()).status_code, 401)
        self.assertEqual(self.client.post('/api/webhooks/pipedrive/deal', data=DEAL, content_type='application/json').status_code, 401)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_imports_signed_deal_once(self):
        r = self.post(DEAL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['status'], 'processed', r.json())
        sale = Sale.objects.get()
        self.assertEqual((sale.amount, sale.date, sale.installments_count, sale.payment_method, sale.pipedrive_id),
                         (Decimal('28996.98'), date(2026, 11, 19), 10, 'PARCELADO NO ASAAS', 1234))
        self.assertEqual((sale.contact.document, sale.contact.email, sale.contact.pipedrive_id), ('12345678000190', 'fulano@empresa.com', 567))
        self.assertEqual((sale.product.name, sale.salesperson_id), ('ASSESSORIAS', self.renato.pk))
        self.assertEqual(Commission.objects.get().percent, Decimal('10'))
        self.assertFalse(Transaction.objects.exists())  # no dates: no receivables
        self.assertEqual(self.post(DEAL).json()['status'], 'ignored')  # Pipedrive retry
        self.assertEqual(Sale.objects.count(), 1)

    def test_reuses_contact_by_document_and_product_by_name(self):
        Contact.objects.create(name='Fulano', document='12345678000190')
        Product.objects.create(name='Assessorias')
        self.post(DEAL)
        self.assertEqual((Contact.objects.count(), Product.objects.count()), (1, 1))
        self.assertEqual(Contact.objects.get().pipedrive_id, 567)

    def test_receivables_when_dates_come(self):
        PipedriveConfig.objects.update(subgroup=self.subgroup)
        r = self.post({**DEAL, 'down_payment': '2.996,98', 'down_payment_date': '2026-11-20', 'first_installment_date': '2026-12-10'})
        self.assertEqual(r.json()['status'], 'processed', r.json())
        txs = Transaction.objects.order_by('date')
        self.assertEqual(txs.count(), 11)
        self.assertEqual((txs[0].amount, txs[0].date), (Decimal('2996.98'), date(2026, 11, 20)))
        self.assertEqual(sum(t.amount for t in txs), Decimal('28996.98'))

    def test_error_is_logged_and_can_be_reprocessed(self):
        r = self.post({**DEAL, 'company_document': '00.000.000/0001-00'})
        self.assertEqual((r.status_code, r.json()['status']), (200, 'error'))
        self.assertIn('CNPJ', r.json()['message'])
        event = WebhookEvent.objects.get()
        Company.objects.filter(pk=self.company.pk).update(cnpj='00000000000100')
        r = self.client.post(f'/api/integrations/events/{event.pk}/reprocess', headers=self.auth())
        self.assertEqual(r.json()['status'], 'processed', r.json())
        self.assertEqual(Sale.objects.count(), 1)

    def test_missing_fields_and_unknown_seller(self):
        self.assertEqual(self.post({'deal_id': 1}).json()['status'], 'error')
        r = self.post({**DEAL, 'owner_name': 'Ninguém'}).json()
        self.assertEqual(r['status'], 'processed')
        self.assertIn('não encontrado', r['message'])
        self.assertFalse(Commission.objects.exists())

    def test_admin_only(self):
        member = User.objects.create_user(email='f@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.assertEqual(self.client.get('/api/integrations/events', headers=self.auth(member)).status_code, 403)

    def test_trailing_slash_url(self):
        r = self.client.post('/api/webhooks/pipedrive/deal/', data=DEAL, content_type='application/json',
                             headers={'Authorization': self.basic})
        self.assertEqual((r.status_code, r.json()['status']), (200, 'processed'), r.content)
