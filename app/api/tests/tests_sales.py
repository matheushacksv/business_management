from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import selectors as finance_selectors
from apps.finance import services as finance
from apps.finance.models import Group, Transaction, TransactionSeries, TransactionStatus
from apps.sales import services
from apps.sales.models import Product, Sale, SaleEvent, Salesperson
from apps.users.models import Role, User

D = Decimal
MEMORY_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class SalesBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.legal = User.objects.create_user(email='leg@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='B', cnpj='11222333000181')
        for user in (self.finance, self.manager, self.legal):
            user.companies.add(self.company)
        self.client_contact = finance.create_contact_service(name='Elos Eletrotécnica')
        self.advisory = services.create_product_service(name='Assessoria')
        self.amanda = services.create_salesperson_service(name='Amanda')
        self.revenue = finance.create_subgroup_service(name='Mentorias', group=Group.OPERATING_REVENUE)

    def sale(self, company=None, amount='30000.00', day=date(2026, 1, 15), **extra):
        return services.create_sale_service(
            user=self.admin, company_id=(company or self.company).pk, date=day, amount=D(amount), **extra
        )

    def req(self, method, url, data=None, user=None):
        kwargs = {'headers': auth_for(user or self.finance)}
        if data is not None:
            kwargs.update(data=data, content_type='application/json')
        return getattr(self.client, method)(url, **kwargs)


class ProductAndSalespersonTests(SalesBase):
    def test_product_crud(self):
        created = self.req('post', '/api/product', {'name': '  Low   Ticket '})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['name'], 'Low Ticket')
        pid = created.json()['id']

        self.assertEqual(self.req('patch', f'/api/product/{pid}', {'active': False}).json()['active'], False)
        names = [p['name'] for p in self.req('get', '/api/product?active=true').json()]
        self.assertEqual(names, ['Assessoria'])
        self.assertEqual(self.req('delete', f'/api/product/{pid}').status_code, 204)

    def test_product_name_unique_case_insensitive(self):
        self.assertEqual(self.req('post', '/api/product', {'name': 'ASSESSORIA'}).status_code, 400)

    def test_product_in_use_cannot_be_deleted(self):
        self.sale(product_id=self.advisory.pk)

        self.assertEqual(self.req('delete', f'/api/product/{self.advisory.pk}').status_code, 400)
        self.assertTrue(Product.objects.filter(pk=self.advisory.pk).exists())

    def test_empty_name_returns_422(self):
        self.assertEqual(self.req('post', '/api/product', {'name': ''}).status_code, 422)

    def test_salesperson_crud_with_user_link(self):
        created = self.req('post', '/api/salesperson', {'name': 'Henrique', 'user_id': self.finance.pk})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['user_id'], self.finance.pk)
        sid = created.json()['id']

        unlinked = self.req('patch', f'/api/salesperson/{sid}', {'user_id': None, 'name': None})
        self.assertEqual(unlinked.json()['user_id'], None)
        self.assertEqual(unlinked.json()['name'], 'Henrique')

    def test_salesperson_name_unique(self):
        self.assertEqual(self.req('post', '/api/salesperson', {'name': 'amanda'}).status_code, 400)

    def test_manager_can_view_but_not_create(self):
        self.assertEqual(self.req('get', '/api/product', user=self.manager).status_code, 200)
        self.assertEqual(self.req('post', '/api/product', {'name': 'X'}, user=self.manager).status_code, 403)


class SaleCrudTests(SalesBase):
    def body(self, **overrides):
        data = {
            'company_id': self.company.pk, 'date': '2024-09-03', 'amount': '9138.80',
            'contact_id': self.client_contact.pk, 'product_id': self.advisory.pk,
            'salesperson_id': self.amanda.pk, 'payment_method': ' BOLETO - ASAAS ',
            'payment_terms': '4 parcelas', 'installments_count': 4,
        }
        data.update(overrides)
        return data

    def test_create_sale(self):
        response = self.req('post', '/api/sale', self.body())

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(D(data['amount']), D('9138.80'))
        self.assertEqual(data['contact_name'], 'Elos Eletrotécnica')
        self.assertEqual(data['product_name'], 'Assessoria')
        self.assertEqual(data['salesperson_name'], 'Amanda')
        self.assertEqual(data['payment_method'], 'BOLETO - ASAAS')
        self.assertEqual(data['status'], 'active')
        self.assertEqual(D(data['received_amount']), D('0'))
        self.assertEqual(D(data['pending_amount']), D('9138.80'))

    def test_create_validation(self):
        cases = {
            'zero amount': (self.body(amount='0'), 422),
            'invalid status': (self.body(status='lost'), 422),
            'non existing product': (self.body(product_id=999999), 400),
            'non existing salesperson': (self.body(salesperson_id=999999), 400),
            'non existing contact': (self.body(contact_id=999999), 400),
            'not linked company': (self.body(company_id=self.other_company.pk), 404),
        }
        for name, (body, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.req('post', '/api/sale', body).status_code, status)
        self.assertFalse(Sale.objects.exists())

    def test_list_filters_and_scope(self):
        a = self.sale(product_id=self.advisory.pk, salesperson_id=self.amanda.pk, contact_id=self.client_contact.pk)
        low = services.create_product_service(name='Low Ticket')
        b = self.sale(product_id=low.pk, day=date(2026, 3, 1), status='canceled')
        self.sale(company=self.other_company)

        def ids(query):
            response = self.req('get', f'/api/sale?{query}')
            self.assertEqual(response.status_code, 200, response.content)
            return [s['id'] for s in response.json()['items']]

        self.assertCountEqual(ids(''), [a.pk, b.pk])
        self.assertEqual(ids(f'product_id={self.advisory.pk}'), [a.pk])
        self.assertEqual(ids(f'salesperson_id={self.amanda.pk}'), [a.pk])
        self.assertEqual(ids('status=canceled'), [b.pk])
        self.assertEqual(ids('date_from=2026-02-01'), [b.pk])
        self.assertEqual(ids('search=elos'), [a.pk])
        self.assertEqual(ids('ordering=date'), [a.pk, b.pk])

    def test_get_update_delete(self):
        sale = self.sale()

        self.assertEqual(self.req('get', f'/api/sale/{sale.pk}').status_code, 200)
        updated = self.req('patch', f'/api/sale/{sale.pk}', {'status': 'canceled', 'notes': ' desistiu '})
        self.assertEqual(updated.json()['status'], 'canceled')
        self.assertEqual(updated.json()['notes'], 'desistiu')
        self.assertEqual(self.req('patch', f'/api/sale/{sale.pk}', {'amount': None}).status_code, 422)
        self.assertEqual(self.req('delete', f'/api/sale/{sale.pk}').status_code, 204)

    def test_other_company_sale_returns_404(self):
        sale = self.sale(company=self.other_company)

        for method, data in (('get', None), ('patch', {'notes': 'x'}), ('delete', None)):
            with self.subTest(method=method):
                self.assertEqual(self.req(method, f'/api/sale/{sale.pk}', data).status_code, 404)

    def test_legal_can_view_but_not_change(self):
        sale = self.sale()

        self.assertEqual(self.req('get', f'/api/sale/{sale.pk}', user=self.legal).status_code, 200)
        self.assertEqual(self.req('patch', f'/api/sale/{sale.pk}', {'notes': 'x'}, user=self.legal).status_code, 403)

    def test_list_query_count_constant(self):
        for _ in range(5):
            self.sale(product_id=self.advisory.pk, salesperson_id=self.amanda.pk, contact_id=self.client_contact.pk)

        with self.assertNumQueries(3):  # user + count + page (totals are annotations)
            self.req('get', '/api/sale')

    def test_history_records_user(self):
        sale = services.create_sale_service(user=self.finance, company_id=self.company.pk,
                                            date=date(2026, 1, 1), amount=D('10'))
        services.update_sale_service(user=self.finance, sale_id=sale.pk, notes='x')

        events = SaleEvent.objects.filter(pgh_obj_id=sale.pk).order_by('pgh_id')
        self.assertEqual([e.pgh_label for e in events], ['insert', 'update'])
        self.assertEqual({e.pgh_context.metadata['user'] for e in events}, {self.finance.pk})


class ReceivablesTests(SalesBase):
    def generate(self, sale, user=None, **data):
        body = {'subgroup_id': self.revenue.pk, 'first_date': '2026-02-10', 'installments': 10}
        body.update(data)
        return self.req('post', f'/api/sale/{sale.pk}/receivables', body, user=user)

    def test_installments_only(self):
        sale = self.sale(contact_id=self.client_contact.pk)

        response = self.generate(sale)

        self.assertEqual(response.status_code, 201, response.content)
        items = response.json()
        self.assertEqual(len(items), 10)
        self.assertEqual({D(t['amount']) for t in items}, {D('3000.00')})
        self.assertEqual({t['type'] for t in items}, {'inflow'})
        self.assertEqual({t['status'] for t in items}, {'planned'})
        self.assertEqual(items[0]['date'], '2026-02-10')
        self.assertEqual(set(Transaction.objects.values_list('sale_id', flat=True)), {sale.pk})
        self.assertEqual(set(Transaction.objects.values_list('contact_id', flat=True)), {self.client_contact.pk})

    def test_down_payment_plus_installments(self):
        sale = self.sale(amount='12000.00')

        items = self.generate(sale, down_payment='1000.00', down_payment_date='2026-01-15', installments=11).json()

        self.assertEqual(len(items), 12)
        self.assertEqual((items[0]['date'], D(items[0]['amount']), items[0]['reference']),
                         ('2026-01-15', D('1000.00'), 'Entrada'))
        self.assertEqual(sum(D(t['amount']) for t in items), D('12000.00'))

    def test_single_installment(self):
        sale = self.sale(amount='500')

        items = self.generate(sale, installments=1).json()

        self.assertEqual([D(t['amount']) for t in items], [D('500')])

    def test_generates_only_what_is_left(self):
        sale = self.sale(amount='1000')
        self.generate(sale, installments=1, down_payment='0')
        Transaction.objects.update(amount=D('400'))  # partially scheduled

        items = self.generate(sale, installments=2).json()

        self.assertEqual([D(t['amount']) for t in items], [D('300'), D('300')])

    def test_validation(self):
        sale = self.sale(amount='1000')
        cases = {
            'down payment too big': ({'down_payment': '1000'}, 400),
            'non existing subgroup': ({'subgroup_id': 999999}, 400),
            'zero installments': ({'installments': 0}, 422),
            'negative down payment': ({'down_payment': '-1'}, 422),
        }
        for name, (data, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.generate(sale, **data).status_code, status)
        self.assertFalse(Transaction.objects.exists())

    def test_fully_scheduled_returns_400(self):
        sale = self.sale(amount='1000')
        self.generate(sale)

        self.assertEqual(self.generate(sale).status_code, 400)

    def test_received_scheduled_and_pending_totals(self):
        sale = self.sale(amount='1000')
        self.generate(sale, installments=4)
        Transaction.objects.filter(series_index__in=[1, 2]).update(status=TransactionStatus.REALIZED)

        data = self.req('get', f'/api/sale/{sale.pk}').json()

        self.assertEqual(D(data['received_amount']), D('500'))
        self.assertEqual(D(data['scheduled_amount']), D('500'))
        self.assertEqual(D(data['pending_amount']), D('500'))

    def test_list_receivables(self):
        sale = self.sale(amount='1000')
        self.generate(sale, installments=2)

        response = self.req('get', f'/api/sale/{sale.pk}/receivables')

        self.assertEqual([D(t['amount']) for t in response.json()], [D('500'), D('500')])

    def test_delete_sale_takes_receivables_along(self):
        sale = self.sale()
        self.generate(sale, installments=3)
        Transaction.objects.filter(sale=sale).update(status='realized')  # paid ones go too

        self.assertEqual(self.req('delete', f'/api/sale/{sale.pk}').status_code, 204)

        self.assertFalse(Sale.objects.filter(pk=sale.pk).exists())
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(TransactionSeries.objects.exists())

    def test_permissions(self):
        sale = self.sale()

        self.assertEqual(self.generate(sale, user=self.manager).status_code, 403)
        self.assertEqual(self.req('get', f'/api/sale/{sale.pk}/receivables', user=self.legal).status_code, 403)
        self.assertFalse(Transaction.objects.exists())


class SalesReportTests(SalesBase):
    def test_sold_vs_received(self):
        jan = self.sale(amount='1000', day=date(2026, 1, 10))
        self.sale(amount='500', day=date(2026, 3, 5))
        self.sale(amount='9999', day=date(2026, 1, 10), company=self.other_company)
        finance.create_series_service(
            user=self.admin, kind='installment', count=2, first_date=date(2026, 1, 20), company_id=self.company.pk,
            subgroup_id=self.revenue.pk, type='inflow', total_amount=D('1000'),
        )
        Transaction.objects.update(sale=jan)
        Transaction.objects.filter(series_index=1).update(status=TransactionStatus.REALIZED)

        response = self.req('get', '/api/reports/sales?start=2026-01-01&end=2026-03-31')

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        periods = {p['period']: p for p in data['periods']}
        self.assertEqual(list(periods), ['2026-01-01', '2026-02-01', '2026-03-01'])
        self.assertEqual((D(periods['2026-01-01']['sold']), D(periods['2026-01-01']['received'])), (D('1000'), D('500')))
        self.assertEqual(periods['2026-01-01']['sales_count'], 1)
        self.assertEqual(D(periods['2026-02-01']['received']), D('0'))  # Feb installment still planned
        self.assertEqual(D(data['total_sold']), D('1500'))
        self.assertEqual(D(data['total_received']), D('500'))

    def test_report_filters_by_product(self):
        self.sale(amount='1000', product_id=self.advisory.pk)
        self.sale(amount='300')

        data = self.req('get', f'/api/reports/sales?start=2026-01-01&end=2026-01-31&product_id={self.advisory.pk}').json()

        self.assertEqual(D(data['total_sold']), D('1000'))

    def test_report_requires_sales_and_reports_view(self):
        self.assertEqual(self.req('get', '/api/reports/sales?start=2026-01-01&end=2026-01-31', user=self.legal).status_code, 403)
        self.assertEqual(self.req('get', '/api/reports/sales?start=2026-01-01&end=2026-01-31', user=self.manager).status_code, 200)

    def test_invalid_range_returns_400(self):
        self.assertEqual(self.req('get', '/api/reports/sales?start=2026-02-01&end=2026-01-01').status_code, 400)

    def test_dre_gross_sales_line(self):
        self.sale(amount='1000', day=date(2026, 1, 10))
        self.sale(amount='500', day=date(2026, 1, 20))
        self.sale(amount='9999', day=date(2026, 1, 10), company=self.other_company)
        self.sale(amount='7777', day=date(2025, 1, 10))

        result = finance_selectors.dre_selector(user=self.finance, year=2026)
        line = result['lines'][0]

        self.assertEqual((line['key'], line['kind'], line['label']), ('gross_sales', 'info', 'Faturamento Bruto'))
        self.assertEqual(line['months'][0], D('1500'))
        self.assertEqual(line['total'], D('1500'))
        self.assertEqual(line['percents'], [None] * 12)

    def test_dre_gross_sales_respects_company_filter(self):
        self.sale(amount='1000')
        self.sale(amount='9999', company=self.other_company)

        result = finance_selectors.dre_selector(user=self.admin, year=2026, company_id=[self.other_company.pk])

        self.assertEqual(result['lines'][0]['total'], D('9999'))


@override_settings(STORAGES=MEMORY_STORAGES)
class SaleContractAttachmentTests(SalesBase):
    def test_attach_signed_contract(self):
        sale = self.sale()

        response = self.client.post('/api/attachment', data={
            'target': 'sale', 'target_id': sale.pk,
            'file': SimpleUploadedFile('contrato.pdf', b'%PDF', content_type='application/pdf'),
        }, headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(sale.attachments.count(), 1)
        listed = self.client.get(f'/api/attachment?target=sale&target_id={sale.pk}', headers=auth_for(self.legal))
        self.assertEqual(len(listed.json()), 1)

    def test_other_company_contract_returns_404(self):
        sale = self.sale(company=self.other_company)

        response = self.client.post('/api/attachment', data={
            'target': 'sale', 'target_id': sale.pk, 'file': SimpleUploadedFile('c.pdf', b'%PDF'),
        }, headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 404)

    def test_salesperson_model_has_no_login_requirement(self):
        self.assertIsNone(Salesperson.objects.get(name='Amanda').user)
