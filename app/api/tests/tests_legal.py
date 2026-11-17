import datetime as dt
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import selectors, services
from apps.finance.models import Contact, Group, Transaction, TransactionStatus, TransactionType
from apps.legal.models import CaseStage, CollectionCase
from apps.users.models import Role, User


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
        case_id = self.create().json()['id']
        self.assertEqual(self.patch(case_id, stage=CaseStage.FILED).status_code, 200)
        self.assertEqual(self.patch(case_id, stage=CaseStage.AGREEMENT).status_code, 400)
        agreement = 'R$ 20.000,00 em 10x de 2.000, primeiro vencimento 10/12'
        response = self.patch(case_id, stage=CaseStage.AGREEMENT, agreement=agreement)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['stage'], 'agreement')

        self.client.post(f'/api/collection-case/{case_id}/comments', data={'text': 'Audiência marcada'},
                         content_type='application/json', headers=self.auth)
        comments = self.client.get(f'/api/collection-case/{case_id}/comments', headers=self.auth).json()
        texts = [c['text'] for c in comments]  # newest first
        self.assertEqual(texts[0], 'Audiência marcada')
        self.assertIn(agreement, texts[1])
        self.assertTrue(texts[2].startswith('Etapa: Nova Ação → Ação Protocolada'))
        self.assertEqual(comments[0]['author_name'], 'admin@test.com')

    def test_delete_returns_installments_to_reports(self):
        case_id = self.create().json()['id']
        response = self.client.delete(f'/api/collection-case/{case_id}', headers=self.auth)
        self.assertEqual(response.status_code, 204)
        self.open1.refresh_from_db()
        self.assertIsNone(self.open1.collection_case_id)

    def test_list_filters_transactions_and_scope(self):
        case_id = self.create().json()['id']
        listed = self.client.get('/api/collection-case', {'stage': 'new', 'search': 'mar'}, headers=self.auth).json()
        self.assertEqual([c['id'] for c in listed], [case_id])
        self.assertEqual(self.client.get('/api/collection-case', {'stage': 'done'}, headers=self.auth).json(), [])
        txs = self.client.get(f'/api/collection-case/{case_id}/transactions', headers=self.auth).json()
        self.assertEqual([t['id'] for t in txs], [self.open1.pk, self.open2.pk])
        self.assertEqual(txs[0]['collection_case_id'], case_id)

        lawyer = User.objects.create_user(email='jur@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        lawyer.companies.add(self.b)  # other company: does not see the case
        self.auth = auth_for(lawyer)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).json(), [])
        self.assertEqual(self.patch(case_id, stage=CaseStage.FILED).status_code, 404)

    def test_permissions(self):
        accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.auth = auth_for(accountant)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).status_code, 403)
        manager = User.objects.create_user(email='ger@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        manager.companies.add(self.a)
        self.auth = auth_for(manager)
        self.assertEqual(self.client.get('/api/collection-case', headers=self.auth).status_code, 200)
        self.assertEqual(self.create().status_code, 403)
        stages = self.client.get('/api/collection-case/stages', headers=self.auth).json()
        self.assertEqual(len(stages), 8)
