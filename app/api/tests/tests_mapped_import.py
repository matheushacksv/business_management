import datetime as dt
import json
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from ninja_jwt.tokens import AccessToken
from openpyxl import Workbook

from apps.companies.models import Company
from apps.finance import services
from apps.finance.mapped_import import _parse_amount, _parse_date
from apps.finance.models import Account, Contact, Group, Transaction
from apps.users.models import Role, User


class ParsingTests(SimpleTestCase):
    def test_amounts(self):
        cases = {
            '1.234,56': ('1234.56', False), 'R$ -10,00': ('10.00', True), '(10,00)': ('10.00', True),
            '10,00-': ('10.00', True), '1234.56': ('1234.56', False), '1,234.56': ('1234.56', False),
            '1.234': ('1234.00', False), '1.5': ('1.50', False), '-7': ('7.00', True), 12.5: ('12.50', False),
            'abc': (None, False), '': (None, False),
        }
        for raw, (amount, negative) in cases.items():
            with self.subTest(raw=raw):
                parsed, neg = _parse_amount(raw)
                self.assertEqual(parsed, Decimal(amount) if amount else None)
                if amount:
                    self.assertEqual(neg, negative)

    def test_dates(self):
        expected = dt.date(2026, 3, 5)
        for raw in ('05/03/2026', '05/03/26', '2026-03-05', '05-03-2026', '05/03/2026 14:30',
                    dt.datetime(2026, 3, 5, 10), expected, 46086):
            with self.subTest(raw=raw):
                self.assertEqual(_parse_date(raw), expected)
        self.assertIsNone(_parse_date('32/13/2026'))


def csv_file(text: str, name='extrato.csv', encoding='utf-8'):
    return SimpleUploadedFile(name, text.encode(encoding), content_type='text/csv')


class MappedImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'}  # type:ignore
        self.company = Company.objects.create(name='O Henriquecedor', cnpj='11222333000181')
        self.other = Company.objects.create(name='Grupo Enriquecedor', cnpj='81585365000127')
        self.rent = services.create_subgroup_service(name='Aluguel', group=Group.FIXED_COSTS)
        self.mentoring = services.create_subgroup_service(name='Mentorias', group=Group.OPERATING_REVENUE)
        self.itau = Account.objects.create(company=self.company, name='Itaú')
        self.maria = Contact.objects.create(name='Maria Silva')
        self.csv = (
            'Extrato Itaú\n'  # title above the header: detected and skipped
            'Data;Histórico;Categoria;Valor;Situação\n'
            '05/11/2026;Imobiliária XYZ;Aluguel;-3.000,00;Pago\n'
            '06/11/2026;maria silva;Mentórias;1.500,00;Pago\n'
            '07/11/2026;Fulano;Aluguel Sede;-100,00;Pendente\n'
            '31/02/2026;Erro;Aluguel;-1,00;Pago\n'
            '\n'
            '08/11/2026;Beltrano;Mentorias;0,00;Pago\n'
        )

    def mapping(self, **overrides):
        data = {
            'columns': {'date': 0, 'contact': 1, 'subgroup': 2, 'amount': 3, 'status': 4},
            'fixed': {'company': self.company.pk, 'account': self.itau.pk},
            'type_mode': 'sign',
        }
        data.update(overrides)
        return data

    def post(self, url, file, **data):
        return self.client.post(url, data={'file': file, **data}, headers=self.auth)

    def run_import(self, mapping=None, commit=False, file=None):
        response = self.post('/api/transaction-import', file or csv_file(self.csv),
                             mapping=json.dumps(mapping or self.mapping()), commit='true' if commit else 'false')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_inspect_detects_header_and_samples(self):
        response = self.post('/api/transaction-import/inspect', csv_file(self.csv))
        data = response.json()
        self.assertEqual(data['header_row'], 2)
        self.assertEqual([c['header'] for c in data['columns']], ['Data', 'Histórico', 'Categoria', 'Valor', 'Situação'])
        self.assertEqual(data['columns'][3]['samples'], ['-3.000,00', '1.500,00', '-100,00'])
        self.assertEqual(data['total_rows'], 5)  # blank line ignored

    def test_inspect_comma_csv_latin1_and_xlsx(self):
        response = self.post('/api/transaction-import/inspect',
                             csv_file('Data,Descrição,Valor\n01/01/2026,Café,"10,50"\n', encoding='latin-1'))
        self.assertEqual([c['header'] for c in response.json()['columns']], ['Data', 'Descrição', 'Valor'])

        wb = Workbook()
        wb.active.title = 'Resumo'
        sheet = wb.create_sheet('Lançamentos')
        sheet.append(['Data', 'Valor'])
        sheet.append([dt.datetime(2026, 1, 2), 99.9])
        buffer = BytesIO()
        wb.save(buffer)
        xlsx = SimpleUploadedFile('planilha.xlsx', buffer.getvalue())
        data = self.post('/api/transaction-import/inspect', xlsx, sheet='Lançamentos').json()
        self.assertEqual(data['sheets'], ['Resumo', 'Lançamentos'])
        self.assertEqual(data['columns'][0]['samples'], ['02/01/2026'])
        self.assertEqual(data['columns'][1]['samples'], ['99.9'])

    def test_dry_run_reports_errors_unknown_values_and_nothing_is_saved(self):
        data = self.run_import()
        self.assertFalse(data['committed'])
        self.assertEqual(data['valid_count'], 2)
        self.assertEqual({(e['row'], e['code']) for e in data['errors']},
                         {(5, 'unknown'), (6, 'invalid_date'), (8, 'zero_amount')})
        self.assertEqual(data['unknown'], {'subgroup': [{'value': 'Aluguel Sede', 'count': 1}]})
        first = data['preview'][0]
        self.assertEqual((first['type'], first['status'], first['amount']), ('outflow', 'realized', '3000.00'))
        self.assertEqual(data['preview'][1]['subgroup_name'], 'Mentorias')  # accent/case-insensitive match
        self.assertEqual(data['new_contacts'], 1)  # "maria silva" matches Maria Silva
        self.assertFalse(Transaction.objects.exists())

    def test_value_maps_and_commit(self):
        mapping = self.mapping(value_maps={'subgroup': {'aluguel sede': self.rent.pk}})
        data = self.run_import(mapping, commit=True)
        self.assertTrue(data['committed'])
        self.assertEqual(data['created'], 3)
        txs = Transaction.objects.order_by('date')
        self.assertEqual([t.subgroup for t in txs], [self.rent, self.mentoring, self.rent])
        self.assertEqual(txs[2].status, 'planned')  # "Pendente"
        self.assertEqual(txs[1].contact, self.maria)
        self.assertEqual(txs[0].contact.name, 'Imobiliária XYZ')  # created
        self.assertTrue(all(t.account == self.itau and t.company == self.company for t in txs))

    def test_duplicates_are_skipped_by_default(self):
        self.run_import(commit=True)
        again = self.run_import()
        self.assertEqual(again['duplicate_count'], 2)
        self.assertEqual(again['to_create'], 0)
        self.assertTrue(all(row['duplicate'] for row in again['preview']))
        forced = self.run_import(self.mapping(skip_duplicates=False))
        self.assertEqual(forced['to_create'], 2)

    def test_type_from_column_subgroup_and_company_column(self):
        text = 'Data;Tipo;Valor;Sub;Empresa\n01/02/2026;C;10,00;Mentorias;11.222.333/0001-81\n' \
               '02/02/2026;Débito;5,00;Aluguel;grupo enriquecedor\n03/02/2026;X;1,00;Aluguel;O Henriquecedor\n'
        mapping = {'columns': {'date': 0, 'type': 1, 'amount': 2, 'subgroup': 3, 'company': 4}, 'type_mode': 'column'}
        data = self.run_import(mapping, file=csv_file(text))
        self.assertEqual([(r['type'], r['company_name']) for r in data['preview']],
                         [('inflow', 'O Henriquecedor'), ('outflow', 'Grupo Enriquecedor')])
        self.assertEqual(data['unknown'], {'type': [{'value': 'X', 'count': 1}]})
        by_subgroup = self.run_import({**mapping, 'type_mode': 'subgroup'}, file=csv_file(text))
        self.assertEqual([r['type'] for r in by_subgroup['preview']], ['inflow', 'outflow', 'outflow'])

    def test_companies_outside_the_user_scope_are_unknown(self):
        member = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        member.companies.add(self.company)
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(member)}'}  # type:ignore
        data = self.run_import(self.mapping(fixed={'company': self.other.pk}))
        self.assertEqual(data['valid_count'], 0)
        fixed_errors = [e for e in data['errors'] if e['code'] == 'invalid_fixed']
        self.assertEqual([(e['row'], e['field']) for e in fixed_errors], [(3, 'company'), (4, 'company')])

    def test_validation_and_permissions(self):
        bad = self.post('/api/transaction-import', csv_file(self.csv), mapping='{"columns": {}}')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.post('/api/transaction-import', csv_file(self.csv), mapping='nope').status_code, 400)
        txt = SimpleUploadedFile('a.txt', b'x')
        self.assertEqual(self.post('/api/transaction-import/inspect', txt).status_code, 400)
        accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(accountant)}'}  # type:ignore
        self.assertEqual(self.post('/api/transaction-import/inspect', csv_file(self.csv)).status_code, 403)
