import csv
import datetime as dt
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase
from openpyxl import Workbook

from apps.companies.models import Company
from apps.finance.importer import import_spreadsheet
from apps.finance.models import Contact, Group, SubGroup, Transaction, TransactionEvent

D = Decimal


def build_workbook(path, rows):
    wb = Workbook()
    plan = wb.active
    plan.title = 'Plano de Contas'
    plan['B3'] = 'Grupos de Contas'
    plan['C4'], plan['C5'] = 'Mentorias', 'Consultoria'          # operating revenue
    plan['D4'] = 'Rendimentos'                                   # non-operating revenue
    plan['E4'] = 'Comissões'                                     # variable costs
    plan['F4'], plan['F5'] = 'Aluguel', 'Taxas e Tarifas'        # fixed costs
    plan['G4'] = 'Juros'                                         # non-operating expenses

    entries = wb.create_sheet('Lançamentos')
    entries.append([])
    entries.append([None, 'Data', 'Cliente/Fornecedor', 'Valor', 'Tipo', 'Produto/Nº Boleto',
                    'Grupo', 'Subgrupo', 'Status', 'Observações', None])
    for row in rows:
        entries.append([None, *row])
    wb.save(path)


def row(date=dt.datetime(2026, 1, 10), contact='Acme', amount=100.0, type='Entradas', ref='NF 1',
        group='Receitas Operacionais', subgroup='Mentorias', status='Realizado', notes='', company=None):
    return [date, contact, amount, type, ref, group, subgroup, status, notes, company]


class ImporterTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sheet.xlsx'
        self.default = Company.objects.create(name='Default', cnpj='81585365000127')
        self.henri = Company.objects.create(name='O Henriquecedor', cnpj='11222333000181')

    def tearDown(self):
        self.tmp.cleanup()

    def run_import(self, rows):
        build_workbook(self.path, rows)
        return import_spreadsheet(
            self.path, default_company=self.default, companies={'O HENRIQUECEDOR': self.henri}
        )

    def test_imports_valid_row(self):
        result = self.run_import([row(amount=290.4, notes='  CARTÃO   C6 ')])

        self.assertEqual(result.transactions_created, 1)
        tx = Transaction.objects.get()
        self.assertEqual(tx.date, dt.date(2026, 1, 10))
        self.assertEqual(tx.amount, D('290.40'))
        self.assertEqual(tx.type, 'inflow')
        self.assertEqual(tx.status, 'realized')
        self.assertEqual(tx.subgroup.name, 'Mentorias')
        self.assertEqual(tx.contact.name, 'Acme')
        self.assertEqual(tx.notes, 'CARTÃO C6')
        self.assertEqual(tx.company, self.default)

    def test_creates_all_plan_subgroups_with_plan_group(self):
        result = self.run_import([row()])

        self.assertEqual(result.subgroups_created, 7)
        self.assertEqual(SubGroup.objects.get(name='Aluguel').group, Group.FIXED_COSTS)
        self.assertEqual(SubGroup.objects.get(name='Juros').group, Group.NON_OPERATING_EXPENSES)

    def test_group_comes_from_plan_not_from_row(self):
        # Row says "Custos Variáveis", plan says fixed costs (211 such rows in the real file)
        self.run_import([row(group='Custos Variáveis', subgroup='Taxas e Tarifas', type='Saídas')])

        self.assertEqual(Transaction.objects.get().subgroup.group, Group.FIXED_COSTS)

    def test_reuses_existing_subgroups(self):
        SubGroup.objects.create(name='Aluguel', group=Group.FIXED_COSTS)

        result = self.run_import([row()])

        self.assertEqual(result.subgroups_created, 6)
        self.assertEqual(SubGroup.objects.filter(name='Aluguel').count(), 1)

    def test_company_mapping_and_default(self):
        self.run_import([row(company='O HENRIQUECEDOR'), row(company=None)])

        self.assertEqual(
            sorted(Transaction.objects.values_list('company__name', flat=True)),
            ['Default', 'O Henriquecedor'],
        )

    def test_unmapped_company_aborts(self):
        with self.assertRaisesMessage(ValueError, 'GRUPO ENRIQUECEDOR'):
            self.run_import([row(company='GRUPO ENRIQUECEDOR')])

        self.assertFalse(Transaction.objects.exists())

    def test_refuses_when_transactions_exist(self):
        self.run_import([row()])

        with self.assertRaisesMessage(ValueError, 'already exist'):
            self.run_import([row()])

    def test_contacts_deduplicated_case_and_spaces(self):
        result = self.run_import([row(contact='Pipedrive'), row(contact=' pipedrive '), row(contact='PIPEDRIVE')])

        self.assertEqual(result.contacts_created, 1)
        self.assertEqual(Contact.objects.get().name, 'Pipedrive')
        self.assertEqual(Transaction.objects.filter(contact__isnull=False).count(), 3)

    def test_existing_contact_is_reused(self):
        Contact.objects.create(name='Acme')

        result = self.run_import([row(contact='ACME')])

        self.assertEqual(result.contacts_created, 0)

    def test_missing_contact_is_allowed(self):
        self.run_import([row(contact=None)])

        self.assertIsNone(Transaction.objects.get().contact)

    def test_installment_date_reference_restored(self):
        self.run_import([row(ref=dt.datetime(2026, 6, 3)), row(ref='--'), row(ref='  NF  22 ')])

        self.assertEqual(
            sorted(Transaction.objects.values_list('reference', flat=True)), ['', '3/6', 'NF 22']
        )

    def test_invalid_rows_are_skipped_with_reason(self):
        result = self.run_import([
            row(date=None),
            row(date='30/00/2025'),
            row(amount=0),
            row(amount='PAGO'),
            row(amount=None),
            row(type=None),
            row(status=None),
            row(subgroup=None),
            row(subgroup='Receitas Operacionais'),
            row(),
        ])

        self.assertEqual(result.transactions_created, 1)
        self.assertEqual([s.reason.split(':')[0] for s in result.skipped], [
            'missing date', 'invalid date', 'zero amount', 'invalid amount', 'invalid amount',
            'invalid type', 'invalid status', 'missing subgroup', 'unknown subgroup',
        ])
        self.assertEqual(result.skipped[0].row, 3)

    def test_blank_rows_are_ignored(self):
        result = self.run_import([[None] * 10, row(), [None, ' ', None, None, None, None, None, None, None, None]])

        self.assertEqual(result.transactions_created, 1)
        self.assertEqual(result.skipped, [])

    def test_amount_rounded_to_cents(self):
        self.run_import([row(amount=10.005)])

        self.assertEqual(Transaction.objects.get().amount, D('10.01'))

    def test_history_marks_import_source(self):
        self.run_import([row()])

        event = TransactionEvent.objects.get()
        self.assertEqual(event.pgh_label, 'insert')
        self.assertEqual(event.pgh_context.metadata['source'], 'spreadsheet_import')


class ImportCommandTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'sheet.xlsx'
        Company.objects.create(name='Default', cnpj='81585365000127')
        Company.objects.create(name='O Henriquecedor', cnpj='11222333000181')
        build_workbook(self.path, [row(), row(company='O HENRIQUECEDOR'), row(amount=0)])

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        out = StringIO()
        call_command('import_spreadsheet', str(self.path), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_saves_nothing(self):
        output = self.call('--default-company', '81.585.365/0001-27',
                           '--company', 'O HENRIQUECEDOR=11.222.333/0001-81')

        self.assertIn('2 imported, 1 skipped', output)
        self.assertIn('Dry-run', output)
        self.assertFalse(Transaction.objects.exists())
        self.assertFalse(SubGroup.objects.exists())

    def test_commit_persists(self):
        self.call('--default-company', '81585365000127',
                  '--company', 'O HENRIQUECEDOR=11222333000181', '--commit')

        self.assertEqual(Transaction.objects.count(), 2)

    def test_skipped_report_csv(self):
        report = Path(self.tmp.name) / 'skipped.csv'

        self.call('--default-company', '81585365000127',
                  '--company', 'O HENRIQUECEDOR=11222333000181', '--skipped-report', str(report))

        with open(report, encoding='utf-8') as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][:2], ['row', 'reason'])
        self.assertEqual(rows[1][:2], ['5', 'zero amount'])

    def test_unknown_company_cnpj_errors(self):
        with self.assertRaisesMessage(CommandError, 'not found'):
            self.call('--default-company', '00000000000000')

    def test_unmapped_company_name_errors(self):
        with self.assertRaisesMessage(CommandError, 'O HENRIQUECEDOR'):
            self.call('--default-company', '81585365000127')

    def test_invalid_mapping_format_errors(self):
        with self.assertRaisesMessage(CommandError, 'NAME=CNPJ'):
            self.call('--default-company', '81585365000127', '--company', 'no-equals-sign')
