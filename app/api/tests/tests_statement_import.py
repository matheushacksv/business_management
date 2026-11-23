from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Account, Contact, Group, StatementRule, Transaction, TransactionStatus, TransactionType
from apps.finance.statement_import import parse_c6_text
from apps.users.models import User

C6_TEXT = """
                                                     EMPRESA TESTE • CNPJ: 81.585.365/0001-27
 Novembro 2026 ( 04/11/2026 - 19/11/2026 )                           Entradas: R$ 1.500,00 •   Saídas: R$ 300,00
 Data   Data   Tipo   Descrição   Valor
  04/11     04/11     Entrada PIX       Pix recebido de CLIENTE UM                         R$ 1.000,00
  05/11     05/11     Saída PIX         Pix enviado para FORNECEDOR XYZ                   -R$ 300,00
  06/11     06/11     Entrada PIX       Pix recebido de EMPRESA DOIS LTDA                  R$ 500,00
 Saldo contábil do dia 06/11/26                                                            R$ 1.200,00
"""

OFX = """OFXHEADER:100
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261110120000<TRNAMT>-89.90<FITID>1<MEMO>CONTA DE LUZ
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261111<TRNAMT>250,00<FITID>2<MEMO>RECEBIMENTO DE TED
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""


class StatementImportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'}  # type:ignore
        self.company = Company.objects.create(name='Empresa Teste', cnpj='81585365000127')
        self.other = Company.objects.create(name='Empresa Dois LTDA', cnpj='11222333000181')
        self.account = Account.objects.create(company=self.company, name='C6')
        self.sales = services.create_subgroup_service(name='Vendas', group=Group.OPERATING_REVENUE)
        self.supplies = services.create_subgroup_service(name='Materiais', group=Group.VARIABLE_COSTS)
        self.customer = Contact.objects.create(name='Cliente Um')

    def analyze(self, content: bytes, name='extrato.ofx'):
        r = self.client.post('/api/statement-import/analyze', data={
            'account_id': self.account.pk, 'file': SimpleUploadedFile(name, content)}, headers=self.auth)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def commit(self, lines):
        return self.client.post('/api/statement-import', data={'account_id': self.account.pk, 'lines': lines},
                                content_type='application/json', headers=self.auth)

    def test_c6_text_reads_lines_year_and_totals(self):
        st = parse_c6_text(C6_TEXT)
        self.assertEqual(st.cnpj, '81585365000127')
        self.assertEqual(st.totals, (Decimal('1500.00'), Decimal('300.00')))
        self.assertEqual([(l.date, l.amount, l.type, l.party) for l in st.lines], [
            (date(2026, 11, 4), Decimal('1000.00'), TransactionType.INFLOW, 'CLIENTE UM'),
            (date(2026, 11, 5), Decimal('300.00'), TransactionType.OUTFLOW, 'FORNECEDOR XYZ'),
            (date(2026, 11, 6), Decimal('500.00'), TransactionType.INFLOW, 'EMPRESA DOIS LTDA'),
        ])

    def test_ofx_suggestions_settle_transfer_and_rules(self):
        installment = services.create_transaction_service(
            user=self.admin, company_id=self.company.pk, subgroup_id=self.sales.pk, date=date(2026, 11, 5),
            amount=Decimal('250'), type=TransactionType.INFLOW, contact_id=self.customer.pk)
        StatementRule.objects.create(key='conta de luz', type=TransactionType.OUTFLOW, subgroup=self.supplies)
        lines = self.analyze(OFX.encode('latin-1'))['lines']
        self.assertEqual([(l['description'], l['action'], l['subgroup_id'], l['match_id']) for l in lines], [
            ('CONTA DE LUZ', 'create', self.supplies.pk, None),  # learned rule
            ('RECEBIMENTO DE TED', 'settle', None, installment.pk),  # planned installment, paid 6 days late
        ])
        r = self.commit(lines)
        self.assertEqual(r.json(), {'created': 1, 'settled': 1, 'transfers': 0, 'skipped': 0})
        installment.refresh_from_db()
        self.assertEqual((installment.status, installment.date, installment.account_id),
                         (TransactionStatus.REALIZED, date(2026, 11, 11), self.account.pk))
        # importing the same file again: everything is a duplicate
        again = self.analyze(OFX.encode('latin-1'))['lines']
        self.assertEqual([(l['duplicate'], l['action']) for l in again], [(True, 'skip'), (True, 'skip')])

    def test_group_company_becomes_a_transfer_and_subgroup_is_learned(self):
        st_lines = self.analyze_text()
        by_party = {l['party']: l for l in st_lines}
        self.assertEqual((by_party['EMPRESA DOIS LTDA']['action'], by_party['EMPRESA DOIS LTDA']['company_id']),
                         ('transfer', self.other.pk))
        supplier = by_party['FORNECEDOR XYZ']
        self.assertEqual(self.commit([{**supplier, 'action': 'create'}]).status_code, 400)  # subgroup required
        by_party['CLIENTE UM'].update(subgroup_id=self.sales.pk)
        supplier.update(subgroup_id=self.supplies.pk)
        r = self.commit(list(by_party.values()))
        self.assertEqual(r.json(), {'created': 2, 'settled': 0, 'transfers': 1, 'skipped': 0}, r.content)
        leg = Transaction.objects.get(company=self.other)
        self.assertEqual((leg.type, leg.amount, leg.transfer_id is not None), (TransactionType.OUTFLOW, Decimal('500.00'), True))
        self.assertEqual(Transaction.objects.get(reference='Pix enviado para FORNECEDOR XYZ').contact.name, 'FORNECEDOR XYZ')
        self.assertTrue(StatementRule.objects.filter(key='pix enviado para fornecedor xyz', subgroup=self.supplies).exists())

    def analyze_text(self):
        from unittest.mock import patch
        with patch('apps.finance.statement_import._read_c6_pdf', lambda data: parse_c6_text(C6_TEXT)):
            return self.analyze(b'%PDF-1.4 fake', name='extrato.pdf')['lines']

    def test_unknown_format(self):
        r = self.client.post('/api/statement-import/analyze', data={
            'account_id': self.account.pk, 'file': SimpleUploadedFile('x.txt', b'hello')}, headers=self.auth)
        self.assertEqual(r.status_code, 400)
