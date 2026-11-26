import datetime as dt
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import selectors, services
from apps.finance.models import Contact, Group, Transaction, TransactionStatus, TransactionType
from apps.legal.models import ChecklistItem, CollectionCase, LegalStage
from apps.users.models import Role, User


def st(name):  # stages seeded by migration 0005
    return LegalStage.objects.get(name=name).pk


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class CollectionCaseTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.auth = auth_for(self.admin)
        self.a = Company.objects.create(name='A', cnpj='81585365000127')
        self.b = Company.objects.create(name='B', cnpj='11222333000181')
        self.maria = Contact.objects.create(name='Maria')
        revenue = services.create_subgroup_service(name='Mentoria', group=Group.OPERATING_REVENUE)

        def tx(company, amount, status, month):
            return services.create_transaction_service(
                user=self.admin, company_id=company.pk, subgroup_id=revenue.pk, contact_id=self.maria.pk,
                date=dt.date(2026, month, 10), amount=Decimal(amount), type=TransactionType.INFLOW, status=status,
            )

        self.paid = tx(self.a, '1000', TransactionStatus.REALIZED, 1)
        self.open1 = tx(self.a, '500', TransactionStatus.PLANNED, 2)
        self.open2 = tx(self.a, '500', TransactionStatus.PLANNED, 3)
        self.other_company = tx(self.b, '700', TransactionStatus.PLANNED, 2)

    def payload(self, **overrides):
        data = {
            'company_id': self.a.pk, 'contact_id': self.maria.pk, 'client_company': 'Maria ME',
            'contact_info': '(48) 99999-0000', 'delivered': 'Mentoria 6 meses', 'proposal_amount': '2000.00',
            'paid_amount': '1000.00', 'summary': 'Parou de pagar em fevereiro',
            'drive_link': 'https://drive.google.com/x',
        }
        return {**data, **overrides}

    def create(self, **overrides):
        response = self.client.post('/api/collection-case', data=self.payload(**overrides),
                                    content_type='application/json', headers=self.auth)
        return response

    def patch(self, case_id, **data):
        return self.client.patch(f'/api/collection-case/{case_id}', data=data,
                                 content_type='application/json', headers=self.auth)

    def test_create_links_open_installments_and_leaves_reports(self):
        dre_before = selectors.dre_selector(user=self.admin, year=2026)
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        case = response.json()
        self.assertEqual(Decimal(case['open_amount']), Decimal('1000'))  # only company A, only planned
        self.assertEqual(Decimal(case['received_amount']), Decimal('0'))
        self.assertEqual(set(Transaction.objects.filter(collection_case_id=case['id'])),
                         {self.open1, self.open2})

        dre = selectors.dre_selector(user=self.admin, year=2026)
        revenue = lambda d: next(l for l in d['lines'] if l['key'] == f'group:{Group.OPERATING_REVENUE}')['total']
        self.assertEqual(revenue(dre_before) - revenue(dre), Decimal('1000'))
        flow = selectors.cash_flow_selector(user=self.admin, start=dt.date(2026, 1, 1), end=dt.date(2026, 12, 31),
                                            company_id=[self.a.pk])
        self.assertEqual(flow['closing'], Decimal('1000'))  # only the realized one

        # Received installment counts again, in reports and in the case totals
        services.update_transaction_service(user=self.admin, transaction_id=self.open1.pk,
                                            status=TransactionStatus.REALIZED)
        case = self.client.get(f'/api/collection-case/{case["id"]}', headers=self.auth).json()
        self.assertEqual((Decimal(case['open_amount']), Decimal(case['received_amount'])),
                         (Decimal('500'), Decimal('500')))
        self.assertEqual(revenue(dre_before) - revenue(selectors.dre_selector(user=self.admin, year=2026)),
                         Decimal('500'))

    def test_required_fields(self):
        for field in ('client_company', 'contact_info', 'delivered', 'summary'):
            with self.subTest(field=field):
                self.assertEqual(self.create(**{field: ''}).status_code, 422)
        self.assertEqual(self.create(drive_link='not a link').status_code, 422)
        self.assertEqual(self.create(proposal_amount='-1').status_code, 422)
        self.assertFalse(CollectionCase.objects.exists())

    def test_agreement_stage_requires_agreement_and_logs_moves(self):
        ChecklistItem.objects.update(required=False)  # checklist: ChecklistTests
        case_id = self.create().json()['id']
        self.assertEqual(self.patch(case_id, stage_id=st('Ação Protocolada')).status_code, 200)
        self.assertEqual(self.patch(case_id, stage_id=st('Acordo ou Sentença')).status_code, 400)
        agreement = 'R$ 20.000,00 em 10x de 2.000, primeiro vencimento 10/12'
        response = self.patch(case_id, stage_id=st('Acordo ou Sentença'), agreement=agreement)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['stage_name'], 'Acordo ou Sentença')

        self.client.post(f'/api/collection-case/{case_id}/comments', data={'text': 'Audiência marcada'},
                         content_type='application/json', headers=self.auth)
        comments = self.client.get(f'/api/collection-case/{case_id}/comments', headers=self.auth).json()
        texts = [c['text'] for c in comments]  # newest first
        self.assertEqual(texts[0], 'Audiência marcada')
        self.assertIn(agreement, texts[1])
        self.assertTrue(texts[2].startswith('Etapa: Nova Ação → Ação Protocolada'))
        self.assertEqual(comments[0]['author_name'], 'admin@test.com')

    def test_close_reopen_and_stage_setup(self):
        case_id = self.create().json()['id']
        r = self.patch(case_id, closed=True)
        self.assertEqual((r.json()['closed_at'] is not None, r.json()['stage_name']), (True, 'Nova Ação'))  # keeps its stage
        self.assertIsNone(self.patch(case_id, closed=False).json()['closed_at'])
        # a new stage with the agreement rule
        new = self.client.post('/api/legal-stage', data={'name': 'Mediação', 'position': 1, 'requires_agreement': True},
                               content_type='application/json', headers=self.auth).json()
        self.assertEqual(self.patch(case_id, stage_id=new['id']).status_code, 400)  # agreement missing
        self.assertEqual(self.patch(case_id, stage_id=new['id'], agreement='Acordo em 3x').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/legal-stage/{new["id"]}', headers=self.auth).status_code, 400)  # has a case
        self.patch(case_id, closed=True)
        self.assertEqual(self.client.delete(f'/api/legal-stage/{new["id"]}', headers=self.auth).status_code, 204)
        self.assertEqual(CollectionCase.objects.get(pk=case_id).stage.name, 'Nova Ação')  # concluded case moved

    def test_delete_returns_installments_to_reports(self):
        case_id = self.create().json()['id']
        response = self.client.delete(f'/api/collection-case/{case_id}', headers=self.auth)
        self.assertEqual(response.status_code, 204)
        self.open1.refresh_from_db()
        self.assertIsNone(self.open1.collection_case_id)

    def test_list_filters_transactions_and_scope(self):
        case_id = self.create().json()['id']
        listed = self.client.get('/api/collection-case', {'stage': st('Nova Ação'), 'search': 'mar'}, headers=self.auth).json()
        self.assertEqual([c['id'] for c in listed], [case_id])
        self.assertEqual(self.client.get('/api/collection-case', {'stage': st('Aguardando Juiz')}, headers=self.auth).json(), [])
        txs = self.client.get(f'/api/collection-case/{case_id}/transactions', headers=self.auth).json()
        self.assertEqual([t['id'] for t in txs], [self.open1.pk, self.open2.pk])
        self.assertEqual(txs[0]['collection_case_id'], case_id)

        lawyer = User.objects.create_user(email='jur@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        lawyer.companies.add(self.b)  # other company: does not see the case
        self.auth = auth_for(lawyer)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).json(), [])
        self.assertEqual(self.patch(case_id, stage_id=st('Ação Protocolada')).status_code, 404)

    def test_permissions(self):
        accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.auth = auth_for(accountant)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).status_code, 403)
        manager = User.objects.create_user(email='ger@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        manager.companies.add(self.a)
        self.auth = auth_for(manager)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).status_code, 200)
        self.assertEqual(self.create().status_code, 403)
        stages = self.client.get('/api/legal-stage', headers=self.auth).json()
        self.assertEqual(len(stages), 7)


class ChecklistTests(TestCase):
    setUp, payload, create = CollectionCaseTests.setUp, CollectionCaseTests.payload, CollectionCaseTests.create

    def patch(self, case_id, body):
        return self.client.patch(f'/api/collection-case/{case_id}', data=body, content_type='application/json', headers=self.auth)

    def test_prefill_from_sales_payments_and_overdue(self):
        from apps.sales.models import Product, Sale
        Sale.objects.create(company=self.a, contact=self.maria, date=dt.date(2026, 1, 5), amount=Decimal('2000'),
                            product=Product.objects.create(name='Mentoria'))
        r = self.client.get(f'/api/collection-case/prefill?company_id={self.a.pk}&contact_id={self.maria.pk}', headers=self.auth)
        data = r.json()
        self.assertEqual((Decimal(data['proposal_amount']), Decimal(data['paid_amount'])), (Decimal('2000'), Decimal('1000')))
        self.assertEqual(data['delivered'], 'Mentoria (contrato de 05/01/2026)')
        self.assertIn('2 parcela(s) em atraso desde 10/02/2026, total R$ 1.000,00', data['summary'])

    def test_filed_needs_required_items(self):
        case_id = self.create().json()['id']
        self.assertEqual(self.create(stage_id=st('Ação Protocolada')).status_code, 400)
        r = self.patch(case_id, {'stage_id': st('Ação Protocolada')})
        self.assertEqual(r.status_code, 400)
        self.assertIn('Contrato assinado', str(r.json()))
        items = self.client.get(f'/api/collection-case/{case_id}/checklist', headers=self.auth).json()
        self.assertTrue(next(i for i in items if i['auto'] == 'amounts')['done'])
        auto = next(i for i in items if i['auto'] == 'contract')
        self.assertEqual(self.client.put(f'/api/collection-case/{case_id}/checklist/{auto["item_id"]}', data={'done': True},
                                         content_type='application/json', headers=self.auth).status_code, 400)
        # admin makes the automatic ones optional; manual ones get ticked; responsible set
        ChecklistItem.objects.filter(auto__in=['customer_data', 'contract', 'attempts']).update(required=False)
        for i in items:
            if not i['auto']:
                r = self.client.put(f'/api/collection-case/{case_id}/checklist/{i["item_id"]}', data={'done': True, 'note': 'ok'},
                                    content_type='application/json', headers=self.auth)
                self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.patch(case_id, {'stage_id': st('Ação Protocolada')}).status_code, 400)  # responsible missing
        self.assertEqual(self.patch(case_id, {'responsible_id': self.admin.pk}).json()['responsible_name'], 'admin@test.com')
        self.assertEqual(self.patch(case_id, {'stage_id': st('Ação Protocolada')}).status_code, 200)
        self.assertEqual(self.patch(case_id, {'summary': 'Ainda devendo'}).status_code, 200)

    def test_items_admin_only(self):
        legal = User.objects.create_user(email='j@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        body = {'label': 'Procuração', 'required': True}
        self.assertEqual(self.client.post('/api/legal-checklist-item', data=body, content_type='application/json',
                                          headers=auth_for(legal)).status_code, 403)
        self.assertEqual(self.client.post('/api/legal-checklist-item', data=body, content_type='application/json',
                                          headers=self.auth).status_code, 201)
        names = [r['name'] for r in self.client.get('/api/collection-case/responsibles', headers=auth_for(legal)).json()]
        self.assertEqual(sorted(names), ['admin@test.com', 'j@test.com'])
