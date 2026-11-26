import datetime as dt
import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from ninja_jwt.tokens import AccessToken
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance import services
from apps.finance.contact_merge import run_merges, similarity, write_suggestions
from apps.finance.models import Contact, Group, Transaction, TransactionStatus, TransactionType
from apps.legal.models import CollectionCase
from apps.sales.linking import run_link
from apps.sales.models import Sale
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class ContactMergeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.revenue = services.create_subgroup_service(name='Mentoria', group=Group.OPERATING_REVENUE)
        self.keep = Contact.objects.create(name='ALDM Advogados', notes='cliente antigo')
        self.dup = Contact.objects.create(name='ALMD Advogados (Sammuel)', document='11222333000181',
                                          phone='4899', notes='veio da venda')

    def tx(self, contact, amount, day, ref='', status=TransactionStatus.REALIZED):
        return services.create_transaction_service(
            user=self.admin, company_id=self.company.pk, subgroup_id=self.revenue.pk, contact_id=contact.pk,
            date=dt.date(2025, 1, 1) + dt.timedelta(days=day), amount=Decimal(amount),
            type=TransactionType.INFLOW, status=status, reference=ref,
        )

    def test_merge_endpoint_moves_everything_and_fills_blanks(self):
        tx = self.tx(self.dup, '100', 0)
        sale = Sale.objects.create(company=self.company, contact=self.dup, date=dt.date(2025, 1, 1), amount=100)
        case = CollectionCase.objects.create(company=self.company, contact=self.dup)
        response = self.client.post(f'/api/contact/{self.keep.pk}/merge', data={'source_ids': [self.dup.pk]},
                                    content_type='application/json', headers=auth_for(self.admin))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(Contact.objects.filter(pk=self.dup.pk).exists())
        for obj in (tx, sale, case):
            obj.refresh_from_db()
            self.assertEqual(obj.contact_id, self.keep.pk)
        self.keep.refresh_from_db()
        self.assertEqual((self.keep.document, self.keep.phone), ('11222333000181', '4899'))  # filled; unique doc moved
        self.assertIn('[ALMD Advogados (Sammuel)] veio da venda', self.keep.notes)
        self.assertTrue(self.keep.notes.startswith('cliente antigo'))

    def test_judicial_duplicate_goes_to_the_collection_case(self):
        franciele = Contact.objects.create(name='Franciele Tatiane Advogada')
        agreement = Contact.objects.create(name='Franciele Tatiane Advogada - Acordo Judicial')
        normal = self.tx(franciele, '4000', 0)
        paid = self.tx(agreement, '1000', 30)
        planned = self.tx(agreement, '1000', 60, status=TransactionStatus.PLANNED)
        services.merge_contacts_service(user=self.admin, target_id=franciele.pk, source_ids=[agreement.pk])

        case = CollectionCase.objects.get(contact=franciele)
        self.assertEqual(case.stage.name, 'Acordo ou Sentença')
        self.assertIn('Franciele Tatiane Advogada - Acordo Judicial', case.agreement)
        for tx, case_id in ((normal, None), (paid, case.pk), (planned, case.pk)):
            tx.refresh_from_db()
            self.assertEqual((tx.contact_id, tx.collection_case_id), (franciele.pk, case_id))
        self.assertEqual(case.comments.count(), 1)

        # A second judicial duplicate reuses the open case
        other = Contact.objects.create(name='Franciele Tatiane Advogada (Ação)')
        self.tx(other, '500', 90)
        services.merge_contacts_service(user=self.admin, target_id=franciele.pk, source_ids=[other.pk])
        self.assertEqual(CollectionCase.objects.filter(contact=franciele).count(), 1)
        self.assertEqual(case.transactions.count(), 3)

    def test_merge_needs_change_and_delete(self):
        finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        response = self.client.post(f'/api/contact/{self.keep.pk}/merge', data={'source_ids': [self.dup.pk]},
                                    content_type='application/json', headers=auth_for(finance))
        self.assertEqual(response.status_code, 403)
        bad = self.client.post(f'/api/contact/{self.keep.pk}/merge', data={'source_ids': [self.keep.pk]},
                               content_type='application/json', headers=auth_for(self.admin))
        self.assertEqual(bad.status_code, 400)

    def test_similarity_rules(self):
        self.assertIsNotNone(similarity('VMS | Advocacia', 'VMS Advocacia'))
        self.assertIsNotNone(similarity('ALDM Advogados', 'ALMD Advogados (Sammuel)'))
        self.assertIsNone(similarity('Luni Digital - 2', 'Luni Digital'))  # numbered contracts are distinct
        self.assertIsNone(similarity('VMS Advocacia', 'Elmano Bastos Advocacia'))

    def test_suggestions_keep_the_plain_name_and_file_order_is_fixed(self):
        plain = Contact.objects.create(name='Cimenart Revestimentos')
        judicial = Contact.objects.create(name='Cimenart Revestimentos - Acordo')
        for _ in range(3):
            self.tx(judicial, '10', 0)  # more data on the judicial side
        Sale.objects.create(company=self.company, contact=plain, date=dt.date(2025, 1, 1), amount=30)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'dups.xlsx'
            write_suggestions(path)
            wb = load_workbook(path)
            row = next(r for r in wb.active.iter_rows(min_row=2) if 'Cimenart' in r[0].value)
            self.assertEqual((row[0].value, row[1].value), ('Cimenart Revestimentos', 'Cimenart Revestimentos - Acordo'))
            row[0].value, row[1].value, row[7].value = row[1].value, row[0].value, 'S'  # reviewer swapped them
            wb.save(path)
            run_merges(path, user=None, commit=True)
        self.assertEqual(list(Contact.objects.filter(name__startswith='Cimenart').values_list('name', flat=True)),
                         ['Cimenart Revestimentos'])
        self.assertEqual(CollectionCase.objects.get().transactions.count(), 3)

    def test_suggestions_file_roundtrip_with_chains(self):
        third = Contact.objects.create(name='ALDM Advogados.')
        for contact in (self.keep, self.dup, third):
            self.tx(contact, '10', 0)
        Sale.objects.create(company=self.company, contact=self.dup, date=dt.date(2025, 1, 1), amount=30)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'dups.xlsx'
            # keep x third is skipped: neither has a sale. Both other pairs share dup (a chain)
            self.assertEqual(write_suggestions(path), 2)
            wb = load_workbook(path)
            for row in wb.active.iter_rows(min_row=2):
                row[7].value = 'S'
            wb.save(path)
            dry = run_merges(path, user=None, commit=False)
            self.assertEqual(Contact.objects.count(), 3)  # dry-run
            result = run_merges(path, user=None, commit=True)
        self.assertEqual(len(dry.merged), 2)
        self.assertEqual((len(result.merged), result.errors), (2, []))
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Transaction.objects.values('contact').distinct().count(), 1)


class LinkReceivablesTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.revenue = services.create_subgroup_service(name='Mentoria', group=Group.OPERATING_REVENUE)

    def tx(self, name, amount, date, ref=''):
        contact, _ = Contact.objects.get_or_create(name=name)
        return services.create_transaction_service(
            user=self.admin, company_id=self.company.pk, subgroup_id=self.revenue.pk, contact_id=contact.pk,
            date=date, amount=Decimal(amount), type=TransactionType.INFLOW, status=TransactionStatus.PLANNED,
            reference=ref,
        )

    def sale(self, name, amount, date):
        contact, _ = Contact.objects.get_or_create(name=name)
        return Sale.objects.create(company=self.company, contact=contact, date=date, amount=Decimal(amount))

    def test_links_matching_amounts_overlapping_contracts_and_look_alikes(self):
        d = dt.date
        advisory = self.sale('Dal Maso Adv', '3000', d(2025, 1, 10))
        crm = self.sale('Dal Maso Adv', '400', d(2025, 2, 1))  # overlaps the advisory installments
        for month in (1, 2, 3):
            self.tx('Dal Maso Adv', '1000', d(2025, month, 10), f'{month}/3')
        for month in (2, 3):
            self.tx('Dal Maso Adv', '200', d(2025, month, 5), f'{month - 1}/2')
        look_alike = self.sale('VMS Advocacia', '500', d(2025, 1, 1))
        self.tx('VMS | Advocacia', '500', d(2025, 1, 3))
        wrong = self.sale('Ward Engenharia', '999', d(2025, 1, 1))
        self.tx('Ward Engenharia', '500', d(2025, 1, 3))

        dry = run_link(commit=False)
        self.assertEqual(dry.linked_sales, 3)
        self.assertFalse(Transaction.objects.filter(sale__isnull=False).exists())

        result = run_link(commit=True)
        self.assertEqual((result.linked_sales, [s.pk for s, *_ in result.not_matching]), (3, [wrong.pk]))
        self.assertEqual(sorted(t.amount for t in advisory.receivables.all()), [1000, 1000, 1000])
        self.assertEqual(sorted(t.amount for t in crm.receivables.all()), [200, 200])
        self.assertEqual(look_alike.receivables.count(), 1)
        self.assertEqual(run_link(commit=True).already_linked, 3)  # idempotent
