import datetime as dt
import json
import tempfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from ninja_jwt.tokens import AccessToken
from openpyxl import load_workbook

from apps.attachments import services as attachment_services
from apps.companies.models import Company
from apps.finance import services as finance
from apps.finance.models import Group, Transaction, TransactionType
from apps.finance.tests_importer import build_workbook, row, sale
from apps.sales.models import Sale
from apps.users.models import Role, User

D = Decimal
MEMORY_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class ImportEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='admin@test.com', password='Str@ngPassw8rd2026', role=Role.ADMIN)
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.default = Company.objects.create(name='Default', cnpj='81585365000127')
        self.henri = Company.objects.create(name='O Henriquecedor', cnpj='11222333000181')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'sheet.xlsx'
        build_workbook(path, [row(), row(company='O HENRIQUECEDOR'), row(amount=0)], sales=[sale()])
        self.xlsx = path.read_bytes()

    def upload(self, user=None, companies=None, commit=False, content=None, name='planilha.xlsx', **extra):
        data = {
            'file': SimpleUploadedFile(name, content if content is not None else self.xlsx),
            'default_company_id': self.default.pk,
            'commit': 'true' if commit else 'false',
        }
        if companies is not None:
            data['companies'] = companies if isinstance(companies, str) else json.dumps(companies)
        data.update(extra)
        return self.client.post('/api/import', data=data, headers=auth_for(user or self.admin))

    def test_preview_reports_unmapped_companies_without_saving(self):
        response = self.upload()

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertFalse(data['committed'])
        self.assertEqual(data['company_names'], ['O HENRIQUECEDOR'])
        self.assertEqual(data['unmapped_companies'], ['O HENRIQUECEDOR'])
        self.assertEqual((data['transactions_found'], data['sales_found']), (2, 1))
        self.assertEqual(data['transactions_created'], 0)
        self.assertEqual(data['skipped'], [{'row': 5, 'reason': 'zero amount'}])
        self.assertFalse(Transaction.objects.exists())

    def test_preview_with_mapping_simulates_everything(self):
        data = self.upload(companies={'O HENRIQUECEDOR': self.henri.pk}).json()

        self.assertFalse(data['committed'])
        self.assertEqual(data['unmapped_companies'], [])
        self.assertEqual((data['transactions_created'], data['sales_created'], data['contacts_created']), (2, 1, 2))
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(Sale.objects.exists())

    def test_commit(self):
        data = self.upload(companies={'O HENRIQUECEDOR': self.henri.pk}, commit=True).json()

        self.assertTrue(data['committed'])
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(Transaction.objects.filter(company=self.henri).count(), 1)
        self.assertEqual(Sale.objects.count(), 1)

    def test_commit_with_unmapped_returns_400(self):
        self.assertEqual(self.upload(commit=True).status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_second_commit_returns_400(self):
        self.upload(companies={'O HENRIQUECEDOR': self.henri.pk}, commit=True)

        response = self.upload(companies={'O HENRIQUECEDOR': self.henri.pk}, commit=True)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_invalid_inputs(self):
        cases = {
            'not xlsx extension': ({'name': 'planilha.csv'}, 400),
            'corrupted xlsx': ({'content': b'not a zip'}, 400),
            'companies not json': ({'companies': '{oops'}, 400),
            'companies not ids': ({'companies': '{"A": "x"}'}, 400),
            'unknown mapped company': ({'companies': {'O HENRIQUECEDOR': 999999}}, 400),
            'unknown default company': ({'default_company_id': 999999}, 404),
        }
        for name, (kwargs, status) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.upload(**kwargs).status_code, status)
        self.assertFalse(Transaction.objects.exists())

    def test_workbook_without_required_sheets_returns_400(self):
        from openpyxl import Workbook
        buffer = BytesIO()
        Workbook().save(buffer)

        response = self.upload(content=buffer.getvalue())

        self.assertEqual(response.status_code, 400)
        self.assertIn('missing the sheets', response.json()['detail'][0])

    def test_only_admins_can_import(self):
        self.assertEqual(self.upload(user=self.finance).status_code, 403)

    def test_requires_authentication(self):
        response = self.client.post('/api/import', data={
            'file': SimpleUploadedFile('p.xlsx', self.xlsx), 'default_company_id': self.default.pk,
        })
        self.assertEqual(response.status_code, 401)


class ExportEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.company = Company.objects.create(name='Empresa A', cnpj='81585365000127')
        other = Company.objects.create(name='Empresa B', cnpj='11222333000181')
        self.finance.companies.add(self.company)
        self.manager.companies.add(self.company)
        self.rent = finance.create_subgroup_service(name='Aluguel', group=Group.FIXED_COSTS)
        contact = finance.create_contact_service(name='Imobiliária')
        self.tx = finance.create_transaction_service(
            user=self.admin, company_id=self.company.pk, subgroup_id=self.rent.pk, date=date(2026, 1, 10),
            amount=D('4500.50'), type=TransactionType.OUTFLOW, contact_id=contact.pk, reference='Boleto 1',
            notes='CARTÃO C6', status='realized',
        )
        finance.create_series_service(
            user=self.admin, kind='installment', count=3, first_date=date(2026, 2, 1), company_id=self.company.pk,
            subgroup_id=self.rent.pk, type=TransactionType.OUTFLOW, total_amount=D('300'),
        )
        finance.create_transaction_service(
            user=self.admin, company_id=other.pk, subgroup_id=self.rent.pk, date=date(2026, 1, 1),
            amount=D('1'), type=TransactionType.OUTFLOW,
        )

    def export(self, query='', user=None):
        return self.client.get(f'/api/transaction/export?{query}', headers=auth_for(user or self.finance))

    def rows(self, response):
        ws = load_workbook(BytesIO(response.content)).active
        return [list(r) for r in ws.iter_rows(values_only=True)]

    def test_export_file(self):
        response = self.export()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertRegex(response['Content-Disposition'], r'attachment; filename="lancamentos-\d{4}-\d{2}-\d{2}\.xlsx"')
        rows = self.rows(response)
        self.assertEqual(rows[0][:9], ['Data', 'Cliente/Fornecedor', 'Valor', 'Tipo', 'Produto/Nº Boleto',
                                       'Grupo', 'Subgrupo', 'Status', 'Observações'])
        self.assertEqual(len(rows), 5)  # header + 4 of own company (other company excluded)
        jan = next(r for r in rows[1:] if r[4] == 'Boleto 1')
        self.assertEqual(jan[0], dt.datetime(2026, 1, 10))
        self.assertEqual(jan[1:4], ['Imobiliária', 4500.5, 'Saída'])
        self.assertEqual(jan[5:13], ['Custos Fixos', 'Aluguel', 'Realizado', 'CARTÃO C6',
                                     'Empresa A', '81585365000127', None, None])
        self.assertEqual(sorted(r[12] for r in rows[1:] if r[12]), ['1/3', '2/3', '3/3'])

    def test_export_respects_filters(self):
        rows = self.rows(self.export('status=realized'))

        self.assertEqual(len(rows), 2)

    def test_export_permissions(self):
        self.assertEqual(self.export(user=self.manager).status_code, 403)
        self.assertEqual(self.client.get('/api/transaction/export').status_code, 401)

    def test_export_invalid_filter_returns_422(self):
        self.assertEqual(self.export('ordering=company__cnpj').status_code, 422)

    def test_export_query_count_constant(self):
        with self.assertNumQueries(2):  # user + rows (single select_related query)
            self.export()


@override_settings(STORAGES=MEMORY_STORAGES)
class HistoryEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='admin@test.com', password='Str@ngPassw8rd2026', role=Role.ADMIN)
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other = Company.objects.create(name='B', cnpj='11222333000181')
        for user in (self.finance, self.manager):
            user.companies.add(self.company)
        self.rent = finance.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

    def tx(self, user, company=None):
        return finance.create_transaction_service(
            user=user, company_id=(company or self.company).pk, subgroup_id=self.rent.pk,
            date=date(2026, 1, 10), amount=D('100'), type=TransactionType.OUTFLOW,
        )

    def history(self, target, target_id, user=None):
        return self.client.get(f'/api/history?target={target}&target_id={target_id}', headers=auth_for(user or self.finance))

    def feed(self, query='', user=None):
        return self.client.get(f'/api/history/feed?{query}', headers=auth_for(user or self.admin))

    def test_transaction_history_with_user_and_previous_values(self):
        tx = self.tx(self.finance)
        finance.update_transaction_service(user=self.admin, transaction_id=tx.pk, amount=D('250'), notes='fixed')

        response = self.history('transaction', tx.pk)

        self.assertEqual(response.status_code, 200, response.content)
        events = response.json()
        self.assertEqual([e['action'] for e in events], ['insert', 'update'])
        self.assertEqual([e['user_email'] for e in events], ['fin@test.com', 'admin@test.com'])
        changes = events[1]['changes']
        self.assertEqual(changes['amount'], [100.0, 250.0])  # row_to_json numbers
        self.assertEqual(changes['notes'], ['', 'fixed'])
        self.assertEqual(events[1]['data']['amount'], 250.0)
        self.assertEqual((events[0]['target'], events[0]['target_id']), ('transaction', tx.pk))

    def test_deleted_record_history_visible_to_admin_only(self):
        tx = self.tx(self.finance)
        pk = tx.pk
        finance.delete_transaction_service(user=self.finance, transaction_id=pk)

        admin_view = self.history('transaction', pk, user=self.admin)
        self.assertEqual([e['action'] for e in admin_view.json()], ['insert', 'delete'])
        self.assertEqual(admin_view.json()[1]['user_email'], 'fin@test.com')
        self.assertEqual(self.history('transaction', pk).status_code, 404)

    def test_scope_and_permissions(self):
        other_tx = self.tx(self.admin, company=self.other)
        tx = self.tx(self.finance)

        self.assertEqual(self.history('transaction', other_tx.pk).status_code, 404)
        self.assertEqual(self.history('transaction', tx.pk, user=self.manager).status_code, 403)
        self.assertEqual(self.history('transaction', 999999, user=self.admin).status_code, 404)
        self.assertEqual(self.history('banana', 1).status_code, 422)

    def test_user_history_never_exposes_password(self):
        finance_user = self.finance
        self.client.patch(f'/api/user/{finance_user.pk}', data={'role': 'accountant'},
                          content_type='application/json', headers=auth_for(self.admin))
        finance_user.refresh_from_db()  # a stale instance would save the old role back
        finance_user.set_password('An0ther-Str@ng-Pass')
        finance_user.save()

        events = self.history('user', finance_user.pk, user=self.admin).json()

        self.assertEqual([e['action'] for e in events], ['insert', 'update'])  # password change not tracked
        self.assertEqual(events[1]['changes']['role'], ['finance', 'accountant'])
        for event in events:
            self.assertNotIn('password', event['data'])
            self.assertNotIn('password', event['changes'])

    def test_user_history_requires_users_permission(self):
        self.assertEqual(self.history('user', self.finance.pk).status_code, 403)

    def test_other_targets(self):
        contact = finance.create_contact_service(name='Acme')
        cases = {
            'company': self.company.pk, 'subgroup': self.rent.pk, 'contact': contact.pk,
        }
        for target, pk in cases.items():
            with self.subTest(target=target):
                response = self.history(target, pk, user=self.admin)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()[0]['action'], 'insert')

    def test_import_source_is_shown(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'sheet.xlsx'
        build_workbook(path, [row(subgroup='Aluguel', group='Custos Fixos', type='Saídas')])
        from apps.finance.importer import run_import
        run_import(path, default_company=self.company, companies={}, commit=True)
        tx = Transaction.objects.get()

        event = self.history('transaction', tx.pk, user=self.admin).json()[0]

        self.assertEqual((event['source'], event['user_id']), ('spreadsheet_import', None))

    # Feed

    def test_feed_newest_first_across_models(self):
        tx = self.tx(self.finance)
        with self.captureOnCommitCallbacks(execute=True):
            attachment_services.upload_attachment_service(
                user=self.finance, target='transaction', target_id=tx.pk,
                file=SimpleUploadedFile('nf.pdf', b'%PDF'),
            )

        data = self.feed().json()

        # one DB transaction in tests -> same timestamp; cross-table order is not asserted
        targets = {i['target'] for i in data['items']}
        self.assertTrue({'attachment', 'transaction', 'subgroup', 'user'} <= targets)
        stamps = [i['created_at'] for i in data['items']]
        self.assertEqual(stamps, sorted(stamps, reverse=True))
        self.assertEqual(data['count'], len(data['items']))

    def test_feed_filter_by_user(self):
        self.tx(self.finance)
        self.tx(self.admin)

        items = self.feed(f'user_id={self.finance.pk}').json()['items']

        self.assertEqual([(i['target'], i['user_email']) for i in items], [('transaction', 'fin@test.com')])

    def test_feed_filter_by_target_and_date(self):
        self.tx(self.finance)
        today = dt.date.today().isoformat()

        self.assertEqual({i['target'] for i in self.feed('target=transaction').json()['items']}, {'transaction'})
        self.assertEqual(self.feed(f'date_from={today}&target=transaction').json()['count'], 1)
        self.assertEqual(self.feed('date_to=2000-01-01').json()['count'], 0)

    def test_feed_pagination(self):
        for _ in range(55):
            finance.create_contact_service(name='C')

        first = self.feed('target=contact').json()
        second = self.feed('target=contact&page=2').json()

        self.assertEqual(first['count'], 55)
        self.assertEqual((len(first['items']), len(second['items'])), (50, 5))

    def test_feed_admin_only(self):
        self.assertEqual(self.feed(user=self.finance).status_code, 403)
        self.assertEqual(self.feed('page=0').status_code, 422)
