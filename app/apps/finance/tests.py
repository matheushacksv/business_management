from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.finance import services
from apps.companies.models import Company
from apps.finance.models import (
    Account, Contact, Group, SubGroup, Transaction, TransactionEvent, TransactionStatus,
    TransactionType,
)
from apps.users.models import User


class SubGroupServicesTest(TestCase):
    # Create tests

    def test_create_subgroup(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        self.assertEqual(subgroup.name, 'Rent')
        self.assertEqual(subgroup.group, Group.FIXED_COSTS)
        self.assertTrue(SubGroup.objects.filter(pk=subgroup.pk).exists())

    def test_create_subgroup_strips_name(self):
        subgroup = services.create_subgroup_service(name='  Rent  ', group=Group.FIXED_COSTS)

        self.assertEqual(subgroup.name, 'Rent')

    def test_create_duplicated_subgroup_raises(self):
        services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        with self.assertRaises(ValidationError):
            services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

    def test_create_duplicated_subgroup_after_strip_raises(self):
        services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        with self.assertRaises(ValidationError):
            services.create_subgroup_service(name=' Rent ', group=Group.FIXED_COSTS)

    def test_create_same_name_in_another_group(self):
        services.create_subgroup_service(name='Taxes', group=Group.FIXED_COSTS)
        other = services.create_subgroup_service(name='Taxes', group=Group.VARIABLE_COSTS)

        self.assertEqual(other.group, Group.VARIABLE_COSTS)
        self.assertEqual(SubGroup.objects.filter(name='Taxes').count(), 2)

    # List tests

    def test_list_subgroups(self):
        rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)

        subgroups = services.list_subgroups_service()

        self.assertCountEqual(subgroups, [rent, sales])

    def test_list_subgroups_filtered_by_group(self):
        rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)

        subgroups = services.list_subgroups_service(group=Group.FIXED_COSTS)

        self.assertCountEqual(subgroups, [rent])

    def test_list_empty_subgroups(self):
        self.assertFalse(services.list_subgroups_service().exists())

    # Get tests

    def test_get_subgroup(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        found = services.get_subgroup_service(subgroup_id=subgroup.pk)

        self.assertEqual(found.pk, subgroup.pk)
        self.assertEqual(found.name, 'Rent')

    def test_get_non_existing_subgroup_raises(self):
        with self.assertRaises(SubGroup.DoesNotExist):
            services.get_subgroup_service(subgroup_id=999999)

    # Update tests

    def test_update_subgroup_name(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        updated = services.update_subgroup_service(subgroup_id=subgroup.pk, name=' Paychecks ')

        self.assertEqual(updated.name, 'Paychecks')
        subgroup.refresh_from_db()
        self.assertEqual(subgroup.name, 'Paychecks')

    def test_update_subgroup_group(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

        services.update_subgroup_service(subgroup_id=subgroup.pk, group=Group.VARIABLE_COSTS)

        subgroup.refresh_from_db()
        self.assertEqual(subgroup.group, Group.VARIABLE_COSTS)

    def test_update_subgroup_to_existing_name_raises(self):
        services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        subgroup = services.create_subgroup_service(name='Paychecks', group=Group.FIXED_COSTS)

        with self.assertRaises(ValidationError):
            services.update_subgroup_service(subgroup_id=subgroup.pk, name='Rent')

        subgroup.refresh_from_db()
        self.assertEqual(subgroup.name, 'Paychecks')

    def test_update_non_existing_subgroup_raises(self):
        with self.assertRaises(SubGroup.DoesNotExist):
            services.update_subgroup_service(subgroup_id=999999, name='Rent')

    # Delete tests

    def test_delete_subgroup(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        pk = subgroup.pk

        services.delete_subgroup_service(subgroup_id=pk)

        self.assertFalse(SubGroup.objects.filter(pk=pk).exists())

    def test_delete_non_existing_subgroup_raises(self):
        with self.assertRaises(SubGroup.DoesNotExist):
            services.delete_subgroup_service(subgroup_id=999999)

    def test_delete_subgroup_in_use_raises(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        company = Company.objects.create(name='Test Company', cnpj='81585365000127')
        Transaction.objects.create(
            company=company, subgroup=subgroup, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        with self.assertRaises(ValidationError):
            services.delete_subgroup_service(subgroup_id=subgroup.pk)

        self.assertTrue(SubGroup.objects.filter(pk=subgroup.pk).exists())


class ContactServicesTest(TestCase):
    # Create tests

    def test_create_contact_with_name_only(self):
        contact = services.create_contact_service(name='John Doe')

        self.assertEqual(contact.name, 'John Doe')
        self.assertEqual(contact.document, '')
        self.assertTrue(Contact.objects.filter(pk=contact.pk).exists())

    def test_create_contact_normalizes_fields(self):
        contact = services.create_contact_service(
            name='  John Doe ', company_name=' Acme ', document='81.585.365/0001-27',
            email=' John@Doe.COM ', phone=' 11 99999-9999 ',
        )

        self.assertEqual(contact.name, 'John Doe')
        self.assertEqual(contact.company_name, 'Acme')
        self.assertEqual(contact.document, '81585365000127')
        self.assertEqual(contact.email, 'john@doe.com')
        self.assertEqual(contact.phone, '11 99999-9999')

    def test_create_contact_with_cpf(self):
        contact = services.create_contact_service(name='John Doe', document='123.456.789-09')

        self.assertEqual(contact.document, '12345678909')

    def test_create_duplicated_document_raises(self):
        services.create_contact_service(name='Acme', document='81585365000127')

        with self.assertRaises(ValidationError):
            services.create_contact_service(name='Acme 2', document='81.585.365/0001-27')

    def test_create_many_contacts_without_document(self):
        services.create_contact_service(name='John')
        services.create_contact_service(name='Mary')

        self.assertEqual(Contact.objects.filter(document='').count(), 2)

    def test_create_contacts_with_same_name(self):
        services.create_contact_service(name='John')
        services.create_contact_service(name='John')

        self.assertEqual(Contact.objects.filter(name='John').count(), 2)

    # List tests

    def test_list_contacts(self):
        john = services.create_contact_service(name='John')
        mary = services.create_contact_service(name='Mary')

        self.assertCountEqual(services.list_contacts_service(), [john, mary])

    def test_list_empty_contacts(self):
        self.assertFalse(services.list_contacts_service().exists())

    def test_search_contacts_by_name_case_insensitive(self):
        john = services.create_contact_service(name='John Doe')
        services.create_contact_service(name='Mary')

        self.assertCountEqual(services.list_contacts_service(search='doe'), [john])

    def test_search_contacts_by_company_name(self):
        john = services.create_contact_service(name='John', company_name='Itaú Unibanco')
        services.create_contact_service(name='Mary', company_name='Nubank')

        self.assertCountEqual(services.list_contacts_service(search='itaú'), [john])

    def test_search_contacts_by_document(self):
        acme = services.create_contact_service(name='Acme', document='81585365000127')
        services.create_contact_service(name='Other', document='11222333000181')

        self.assertCountEqual(services.list_contacts_service(search='815853'), [acme])

    # Get tests

    def test_get_contact(self):
        contact = services.create_contact_service(name='John')

        self.assertEqual(services.get_contact_service(contact_id=contact.pk).pk, contact.pk)

    def test_get_non_existing_contact_raises(self):
        with self.assertRaises(Contact.DoesNotExist):
            services.get_contact_service(contact_id=999999)

    # Update tests

    def test_update_contact_fields(self):
        contact = services.create_contact_service(name='John', phone='111')

        services.update_contact_service(
            contact_id=contact.pk, name=' Johnny ', email='JOHNNY@DOE.COM'
        )

        contact.refresh_from_db()
        self.assertEqual(contact.name, 'Johnny')
        self.assertEqual(contact.email, 'johnny@doe.com')
        self.assertEqual(contact.phone, '111')

    def test_update_contact_normalizes_document(self):
        contact = services.create_contact_service(name='Acme')

        services.update_contact_service(contact_id=contact.pk, document='81.585.365/0001-27')

        contact.refresh_from_db()
        self.assertEqual(contact.document, '81585365000127')

    def test_update_contact_to_existing_document_raises(self):
        services.create_contact_service(name='Acme', document='81585365000127')
        other = services.create_contact_service(name='Other', document='11222333000181')

        with self.assertRaises(ValidationError):
            services.update_contact_service(contact_id=other.pk, document='81585365000127')

        other.refresh_from_db()
        self.assertEqual(other.document, '11222333000181')

    def test_update_contact_clear_document(self):
        contact = services.create_contact_service(name='Acme', document='81585365000127')

        services.update_contact_service(contact_id=contact.pk, document='')

        contact.refresh_from_db()
        self.assertEqual(contact.document, '')

    def test_update_non_existing_contact_raises(self):
        with self.assertRaises(Contact.DoesNotExist):
            services.update_contact_service(contact_id=999999, name='John')

    # Delete tests

    def test_delete_contact(self):
        contact = services.create_contact_service(name='John')
        pk = contact.pk

        services.delete_contact_service(contact_id=pk)

        self.assertFalse(Contact.objects.filter(pk=pk).exists())

    def test_delete_non_existing_contact_raises(self):
        with self.assertRaises(Contact.DoesNotExist):
            services.delete_contact_service(contact_id=999999)

    def test_delete_contact_in_use_raises(self):
        contact = services.create_contact_service(name='John')
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        company = Company.objects.create(name='Test Company', cnpj='81585365000127')
        Transaction.objects.create(
            company=company, subgroup=subgroup, contact=contact, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        with self.assertRaises(ValidationError):
            services.delete_contact_service(contact_id=contact.pk)

        self.assertTrue(Contact.objects.filter(pk=contact.pk).exists())


class AccountServicesTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026')
        self.outsider = User.objects.create_user(email='outsider@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='Company A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='Company B', cnpj='11222333000181')
        self.member.companies.add(self.company)

    def create(self, company=None, name='Itaú'):
        return services.create_account_service(
            user=self.admin, company_id=(company or self.company).pk, name=name
        )

    # Create tests

    def test_create_account(self):
        account = services.create_account_service(
            user=self.member, company_id=self.company.pk, name='  Itaú  '
        )

        self.assertEqual(account.name, 'Itaú')
        self.assertEqual(account.company, self.company)

    def test_create_many_accounts_in_same_company(self):
        self.create(name='Itaú')
        self.create(name='Nubank')

        self.assertEqual(Account.objects.filter(company=self.company).count(), 2)

    def test_create_same_name_in_another_company(self):
        self.create(name='Itaú')
        self.create(company=self.other_company, name='Itaú')

        self.assertEqual(Account.objects.filter(name='Itaú').count(), 2)

    def test_create_duplicated_account_raises(self):
        self.create(name='Itaú')

        with self.assertRaises(ValidationError):
            self.create(name='Itaú')

    def test_create_account_in_not_linked_company_raises(self):
        with self.assertRaises(Company.DoesNotExist):
            services.create_account_service(
                user=self.member, company_id=self.other_company.pk, name='Itaú'
            )

        self.assertFalse(Account.objects.exists())

    def test_create_account_in_non_existing_company_raises(self):
        with self.assertRaises(Company.DoesNotExist):
            services.create_account_service(user=self.admin, company_id=999999, name='Itaú')

    # List tests

    def test_admin_lists_all_accounts(self):
        a = self.create()
        b = self.create(company=self.other_company)

        self.assertCountEqual(services.list_accounts_service(user=self.admin), [a, b])

    def test_member_lists_only_linked_company_accounts(self):
        a = self.create()
        self.create(company=self.other_company)

        self.assertCountEqual(services.list_accounts_service(user=self.member), [a])

    def test_outsider_lists_nothing(self):
        self.create()

        self.assertFalse(services.list_accounts_service(user=self.outsider).exists())

    def test_list_accounts_filtered_by_company(self):
        self.create()
        b = self.create(company=self.other_company)

        accounts = services.list_accounts_service(user=self.admin, company_id=self.other_company.pk)

        self.assertCountEqual(accounts, [b])

    def test_member_filter_by_not_linked_company_returns_empty(self):
        self.create(company=self.other_company)

        accounts = services.list_accounts_service(user=self.member, company_id=self.other_company.pk)

        self.assertFalse(accounts.exists())

    # Get tests

    def test_get_account(self):
        account = self.create()

        self.assertEqual(services.get_account_service(user=self.member, account_id=account.pk), account)

    def test_get_account_from_not_linked_company_raises(self):
        account = self.create(company=self.other_company)

        with self.assertRaises(Account.DoesNotExist):
            services.get_account_service(user=self.member, account_id=account.pk)

    def test_get_non_existing_account_raises(self):
        with self.assertRaises(Account.DoesNotExist):
            services.get_account_service(user=self.admin, account_id=999999)

    # Update tests

    def test_update_account_name(self):
        account = self.create()

        services.update_account_service(user=self.member, account_id=account.pk, name=' Itaú CC ')

        account.refresh_from_db()
        self.assertEqual(account.name, 'Itaú CC')

    def test_update_account_to_existing_name_raises(self):
        self.create(name='Itaú')
        account = self.create(name='Nubank')

        with self.assertRaises(ValidationError):
            services.update_account_service(user=self.admin, account_id=account.pk, name='Itaú')

        account.refresh_from_db()
        self.assertEqual(account.name, 'Nubank')

    def test_update_account_from_not_linked_company_raises(self):
        account = self.create(company=self.other_company)

        with self.assertRaises(Account.DoesNotExist):
            services.update_account_service(user=self.member, account_id=account.pk, name='Hacked')

        account.refresh_from_db()
        self.assertEqual(account.name, 'Itaú')

    # Delete tests

    def test_delete_account(self):
        account = self.create()
        pk = account.pk

        services.delete_account_service(user=self.member, account_id=pk)

        self.assertFalse(Account.objects.filter(pk=pk).exists())

    def test_delete_account_from_not_linked_company_raises(self):
        account = self.create(company=self.other_company)

        with self.assertRaises(Account.DoesNotExist):
            services.delete_account_service(user=self.member, account_id=account.pk)

        self.assertTrue(Account.objects.filter(pk=account.pk).exists())

    def test_delete_account_in_use_raises(self):
        account = self.create()
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        Transaction.objects.create(
            company=self.company, account=account, subgroup=subgroup, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        with self.assertRaises(ValidationError):
            services.delete_account_service(user=self.admin, account_id=account.pk)

        self.assertTrue(Account.objects.filter(pk=account.pk).exists())


class TransactionServicesTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='Company A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='Company B', cnpj='11222333000181')
        self.member.companies.add(self.company)
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)
        self.account = Account.objects.create(company=self.company, name='Itaú')
        self.other_account = Account.objects.create(company=self.other_company, name='Bradesco')
        self.contact = services.create_contact_service(name='Landlord')

    def create(self, user=None, company=None, **overrides):
        data = {
            'company_id': (company or self.company).pk, 'subgroup_id': self.rent.pk,
            'date': date(2026, 1, 10), 'amount': Decimal('100.00'), 'type': TransactionType.OUTFLOW,
        }
        data.update(overrides)
        return services.create_transaction_service(user=user or self.admin, **data)

    # Create tests

    def test_create_transaction_with_defaults(self):
        tx = self.create(user=self.member)

        self.assertEqual(tx.company, self.company)
        self.assertEqual(tx.amount, Decimal('100.00'))
        self.assertEqual(tx.status, TransactionStatus.PLANNED)
        self.assertIsNone(tx.account)
        self.assertIsNone(tx.contact)

    def test_create_transaction_full(self):
        tx = self.create(
            account_id=self.account.pk, contact_id=self.contact.pk,
            status=TransactionStatus.REALIZED, reference=' NF 123 ', notes=' paid via pix ',
        )

        self.assertEqual(tx.account, self.account)
        self.assertEqual(tx.contact, self.contact)
        self.assertEqual(tx.status, TransactionStatus.REALIZED)
        self.assertEqual(tx.reference, 'NF 123')
        self.assertEqual(tx.notes, 'paid via pix')

    def test_create_transaction_in_not_linked_company_raises(self):
        with self.assertRaises(Company.DoesNotExist):
            self.create(user=self.member, company=self.other_company)

        self.assertFalse(Transaction.objects.exists())

    def test_create_transaction_with_account_from_another_company_raises(self):
        with self.assertRaises(ValidationError):
            self.create(account_id=self.other_account.pk)

    def test_create_transaction_with_non_existing_subgroup_raises(self):
        with self.assertRaises(ValidationError):
            self.create(subgroup_id=999999)

    def test_create_transaction_with_non_existing_contact_raises(self):
        with self.assertRaises(ValidationError):
            self.create(contact_id=999999)

    def test_create_transaction_with_non_positive_amount_raises(self):
        for amount in (Decimal('0'), Decimal('-10')):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.create(amount=amount)

        self.assertFalse(Transaction.objects.exists())

    # Reversal

    def test_is_reversal(self):
        cases = [
            (self.rent, TransactionType.OUTFLOW, False),
            (self.rent, TransactionType.INFLOW, True),
            (self.sales, TransactionType.INFLOW, False),
            (self.sales, TransactionType.OUTFLOW, True),
        ]
        for subgroup, tx_type, expected in cases:
            with self.subTest(subgroup=subgroup.name, type=tx_type):
                tx = self.create(subgroup_id=subgroup.pk, type=tx_type)
                self.assertEqual(tx.is_reversal, expected)

    # List tests

    def test_admin_lists_all_transactions(self):
        a = self.create()
        b = self.create(company=self.other_company)

        self.assertCountEqual(services.list_transactions_service(user=self.admin), [a, b])

    def test_member_lists_only_linked_company_transactions(self):
        a = self.create()
        self.create(company=self.other_company)

        self.assertCountEqual(services.list_transactions_service(user=self.member), [a])

    def test_list_transactions_filters(self):
        jan = self.create(date=date(2026, 1, 10), status=TransactionStatus.REALIZED)
        feb = self.create(
            date=date(2026, 2, 10), subgroup_id=self.sales.pk, type=TransactionType.INFLOW,
            account_id=self.account.pk, contact_id=self.contact.pk,
        )
        other = self.create(company=self.other_company, date=date(2026, 3, 10))

        cases = {
            'company_id': ({'company_id': self.other_company.pk}, [other]),
            'date_from': ({'date_from': date(2026, 2, 1)}, [feb, other]),
            'date_to': ({'date_to': date(2026, 1, 31)}, [jan]),
            'date_range': ({'date_from': date(2026, 2, 1), 'date_to': date(2026, 2, 28)}, [feb]),
            'status': ({'status': TransactionStatus.REALIZED}, [jan]),
            'type': ({'type': TransactionType.INFLOW}, [feb]),
            'group': ({'group': Group.FIXED_COSTS}, [jan, other]),
            'subgroup_id': ({'subgroup_id': self.sales.pk}, [feb]),
            'account_id': ({'account_id': self.account.pk}, [feb]),
            'contact_id': ({'contact_id': self.contact.pk}, [feb]),
        }
        for name, (filters, expected) in cases.items():
            with self.subTest(filter=name):
                result = services.list_transactions_service(user=self.admin, **filters)
                self.assertCountEqual(result, expected)

    def test_list_transactions_ordered_by_date_desc(self):
        older = self.create(date=date(2026, 1, 1))
        newer = self.create(date=date(2026, 2, 1))

        self.assertEqual(list(services.list_transactions_service(user=self.admin)), [newer, older])

    def test_list_transactions_multi_value_filters(self):
        rent = self.create()
        sales = self.create(subgroup_id=self.sales.pk, type=TransactionType.INFLOW)
        other = self.create(company=self.other_company)
        utilities = services.create_subgroup_service(name='Utilities', group=Group.VARIABLE_COSTS)
        self.create(subgroup_id=utilities.pk)

        cases = {
            'subgroup_id': ({'subgroup_id': [self.rent.pk, self.sales.pk]}, [rent, sales, other]),
            'group': ({'group': [Group.FIXED_COSTS, Group.OPERATING_REVENUE]}, [rent, sales, other]),
            'company_id': ({'company_id': [self.company.pk, self.other_company.pk]}, None),
            'type': ({'type': [TransactionType.INFLOW]}, [sales]),
        }
        everything = list(Transaction.objects.all())
        for name, (filters, expected) in cases.items():
            with self.subTest(filter=name):
                result = services.list_transactions_service(user=self.admin, **filters)
                self.assertCountEqual(result, expected if expected is not None else everything)

    def test_list_transactions_empty_list_filter_is_ignored(self):
        self.create()
        self.create(company=self.other_company)

        result = services.list_transactions_service(user=self.admin, subgroup_id=[])

        self.assertEqual(result.count(), 2)

    def test_list_transactions_multi_company_respects_access(self):
        mine = self.create()
        self.create(company=self.other_company)

        result = services.list_transactions_service(
            user=self.member, company_id=[self.company.pk, self.other_company.pk]
        )

        self.assertCountEqual(result, [mine])

    def test_list_transactions_amount_range(self):
        small = self.create(amount=Decimal('50.00'))
        medium = self.create(amount=Decimal('500.00'))
        big = self.create(amount=Decimal('5000.00'))

        cases = {
            'min': ({'amount_min': Decimal('500')}, [medium, big]),
            'max': ({'amount_max': Decimal('500')}, [small, medium]),
            'range': ({'amount_min': Decimal('100'), 'amount_max': Decimal('1000')}, [medium]),
        }
        for name, (filters, expected) in cases.items():
            with self.subTest(filter=name):
                result = services.list_transactions_service(user=self.admin, **filters)
                self.assertCountEqual(result, expected)

    def test_list_transactions_search(self):
        by_reference = self.create(reference='NF 4521')
        by_notes = self.create(notes='Pago via PIX')
        by_contact = self.create(contact_id=self.contact.pk)
        acme = services.create_contact_service(name='John', company_name='Acme Ltda')
        by_contact_company = self.create(contact_id=acme.pk)
        by_subgroup = self.create(subgroup_id=self.sales.pk, type=TransactionType.INFLOW)

        cases = {
            'reference': ('4521', [by_reference]),
            'notes case insensitive': ('pix', [by_notes]),
            'contact name': ('landlord', [by_contact]),
            'contact company name': ('acme', [by_contact_company]),
            'subgroup name': ('sales', [by_subgroup]),
            'no match': ('zzz', []),
        }
        for name, (term, expected) in cases.items():
            with self.subTest(search=name):
                result = services.list_transactions_service(user=self.admin, search=term)
                self.assertCountEqual(result, expected)

    def test_list_transactions_search_combined_with_filters(self):
        self.create(notes='rent january', date=date(2026, 1, 5))
        feb = self.create(notes='rent february', date=date(2026, 2, 5))

        result = services.list_transactions_service(
            user=self.admin, search='rent', date_from=date(2026, 2, 1)
        )

        self.assertCountEqual(result, [feb])

    def test_list_transactions_ordering(self):
        a = self.create(amount=Decimal('300'), date=date(2026, 1, 1))
        b = self.create(amount=Decimal('100'), date=date(2026, 3, 1))
        c = self.create(amount=Decimal('200'), date=date(2026, 2, 1))

        cases = {
            'amount': [b, c, a],
            '-amount': [a, c, b],
            'date': [a, c, b],
            '-date': [b, c, a],
            'created_at': [a, b, c],
            '-created_at': [c, b, a],
        }
        for ordering, expected in cases.items():
            with self.subTest(ordering=ordering):
                result = services.list_transactions_service(user=self.admin, ordering=ordering)
                self.assertEqual(list(result), expected)

    def test_list_transactions_ordering_ties_are_stable(self):
        txs = [self.create(amount=Decimal('100')) for _ in range(3)]

        result = services.list_transactions_service(user=self.admin, ordering='amount')

        self.assertEqual(list(result), list(reversed(txs)))

    def test_list_transactions_invalid_ordering_raises(self):
        for ordering in ('company__cnpj', 'notes', '?'):
            with self.subTest(ordering=ordering), self.assertRaises(ValidationError):
                services.list_transactions_service(user=self.admin, ordering=ordering)

    # Get tests

    def test_get_transaction(self):
        tx = self.create()

        self.assertEqual(services.get_transaction_service(user=self.member, transaction_id=tx.pk), tx)

    def test_get_transaction_from_not_linked_company_raises(self):
        tx = self.create(company=self.other_company)

        with self.assertRaises(Transaction.DoesNotExist):
            services.get_transaction_service(user=self.member, transaction_id=tx.pk)

    # Update tests

    def test_update_transaction(self):
        tx = self.create()

        services.update_transaction_service(
            user=self.member, transaction_id=tx.pk, amount=Decimal('250.50'),
            status=TransactionStatus.REALIZED, notes=' paid ',
        )

        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal('250.50'))
        self.assertEqual(tx.status, TransactionStatus.REALIZED)
        self.assertEqual(tx.notes, 'paid')
        self.assertEqual(tx.subgroup, self.rent)

    def test_update_transaction_unlink_account(self):
        tx = self.create(account_id=self.account.pk)

        services.update_transaction_service(user=self.admin, transaction_id=tx.pk, account_id=None)

        tx.refresh_from_db()
        self.assertIsNone(tx.account)

    def test_update_transaction_with_account_from_another_company_raises(self):
        tx = self.create()

        with self.assertRaises(ValidationError):
            services.update_transaction_service(
                user=self.admin, transaction_id=tx.pk, account_id=self.other_account.pk
            )

        tx.refresh_from_db()
        self.assertIsNone(tx.account)

    def test_update_transaction_with_non_positive_amount_raises(self):
        tx = self.create()

        with self.assertRaises(ValidationError):
            services.update_transaction_service(user=self.admin, transaction_id=tx.pk, amount=Decimal('0'))

        tx.refresh_from_db()
        self.assertEqual(tx.amount, Decimal('100.00'))

    def test_update_transaction_from_not_linked_company_raises(self):
        tx = self.create(company=self.other_company)

        with self.assertRaises(Transaction.DoesNotExist):
            services.update_transaction_service(user=self.member, transaction_id=tx.pk, notes='hacked')

    # Delete tests

    def test_delete_transaction(self):
        tx = self.create()
        pk = tx.pk

        services.delete_transaction_service(user=self.member, transaction_id=pk)

        self.assertFalse(Transaction.objects.filter(pk=pk).exists())

    def test_delete_transaction_from_not_linked_company_raises(self):
        tx = self.create(company=self.other_company)

        with self.assertRaises(Transaction.DoesNotExist):
            services.delete_transaction_service(user=self.member, transaction_id=tx.pk)

        self.assertTrue(Transaction.objects.filter(pk=tx.pk).exists())

    # Audit history

    def test_history_records_create_update_delete_with_user(self):
        tx = self.create(user=self.member)
        services.update_transaction_service(user=self.member, transaction_id=tx.pk, amount=Decimal('200'))
        services.delete_transaction_service(user=self.admin, transaction_id=tx.pk)

        events = list(TransactionEvent.objects.filter(pgh_obj_id=tx.pk).order_by('pgh_id'))

        self.assertEqual([e.pgh_label for e in events], ['insert', 'update', 'delete'])
        self.assertEqual([e.amount for e in events], [Decimal('100.00'), Decimal('200.00'), Decimal('200.00')])
        self.assertEqual(
            [e.pgh_context.metadata['user'] for e in events],
            [self.member.pk, self.member.pk, self.admin.pk],
        )
