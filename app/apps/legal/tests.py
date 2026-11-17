import datetime as dt
import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance.importer import import_spreadsheet
from apps.finance.models import Transaction, TransactionStatus
from apps.finance.tests_importer import build_workbook, row
from apps.legal.importer import import_collection
from apps.legal.models import CollectionCase


class CollectionImportTest(TestCase):
    def test_undated_rows_get_monthly_dates_and_one_case_per_customer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sheet.xlsx'
            build_workbook(path, [
                row(date=dt.datetime(2026, 7, 16), contact='Carlos Djones', status='Previsto', ref='Entrada'),  # row 3
                row(date=None, contact='Carlos Djones', status='Previsto', ref=dt.datetime(2026, 12, 2)),       # 4: "2/12"
                row(date=None, contact='Carlos Djones', status='Previsto', ref=dt.datetime(2026, 12, 3)),       # 5
                row(date=None, contact='Cimenart Revestimentos', amount=50.0, status='Previsto'),               # 6
                row(date=dt.datetime(2026, 1, 5), contact='NVCON Capital e Investimentos', status='Realizado'),
                row(date=None, contact='NVCON Capital e Investimentos', status='Previsto'),                     # 8
            ])
            wb = load_workbook(path)
            cases = wb.create_sheet('Contratos Cancelados ou Ação de')
            cases.append(['MÊS', 'CLIENTE', 'MOTIVO', 'AÇÃO', '$ CONTRATO', '$ RECEBIDO', 'A RECEBER', 'CLOSER', 'ASSESSOR'])
            cases.append([None, 'Carlos Djones - Ar', 'Inadimplente', 'Sim', 21992, 5041, 16951, 'Renato', 'Amanda'])
            cases.append([None, 'NVCON Capital e Investimentos', 'Inadimplente', 'Sim', 36997, 24911.26, 0, '', ''])
            wb.save(path)

            company = Company.objects.create(name='Default', cnpj='81585365000127')
            import_spreadsheet(path, default_company=company, companies={})
            result = import_collection(path, rows={4, 5, 6, 8}, default_company=company, companies={})

        self.assertEqual(result.rows_imported, 4)
        carlos = Transaction.objects.filter(contact__name='Carlos Djones').order_by('date')
        self.assertEqual([t.date for t in carlos], [dt.date(2026, 7, 16), dt.date(2026, 8, 16), dt.date(2026, 9, 16)])
        self.assertEqual(carlos[1].reference, '2/12')  # installment number kept
        self.assertEqual(len({t.collection_case_id for t in carlos}), 1)  # dated planned row linked too

        by_name = {c.contact.name: c for c in CollectionCase.objects.all()}
        self.assertEqual(set(by_name), {'Carlos Djones', 'Cimenart Revestimentos', 'NVCON Capital e Investimentos'})
        # "Revestimentos" looks like "Investimentos": the stronger NVCON pair must win
        self.assertEqual(by_name['NVCON Capital e Investimentos'].proposal_amount, Decimal('36997.00'))
        self.assertIsNone(by_name['Cimenart Revestimentos'].proposal_amount)
        self.assertEqual(by_name['Carlos Djones'].paid_amount, Decimal('5041.00'))
        nvcon = Transaction.objects.filter(contact__name__startswith='NVCON')
        self.assertEqual({(t.status, t.collection_case_id is not None) for t in nvcon},
                         {(TransactionStatus.REALIZED, False), (TransactionStatus.PLANNED, True)})
        with self.assertRaises(ValueError):  # runs once
            import_collection(path, rows=set(), default_company=company, companies={})
