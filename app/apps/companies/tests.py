from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.companies import services
from apps.companies.models import Company
from apps.users.models import User


class CompanyServicesTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser(
            email='superuser@email.com', password='Str@ngPassw8rd2026'
        )
        self.admin = admin

    # Test create

    def test_create_company(self):
        company = services.create_company_service(
            user=self.admin, name='Test Company',
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )

        self.assertEqual(company.name, 'Test Company')
        self.assertEqual(company.cnpj, '81585365000127')
        self.assertEqual(company.initial_balance, Decimal(0))

    def test_create_duplicate_company(self):
        services.create_company_service(
            user=self.admin, name='Test Company',
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        with self.assertRaises(ValidationError):
            services.create_company_service(
                user=self.admin,
                name='Test Company',
                cnpj='81.585.365/0001-27',
                initial_balance=Decimal(0),
            )

    # Test list/get

    def test_list_companies(self):
        for i in range(2):
            services.create_company_service(
                user=self.admin,
                name=f'Test Company - {i}',
                cnpj=f'81.585.365/0001-2{i}',
                initial_balance=Decimal(0),
            )
        companies = services.list_companies_service(self.admin)

        self.assertEqual(companies.exists(), True)
        self.assertEqual(companies.count(), 2)

    def test_list_empty_companies(self):
        companies = services.list_companies_service(self.admin)

        self.assertEqual(companies.exists(), False)
        self.assertEqual(companies.count(), 0)

    def test_get_company(self):
        created = services.create_company_service(
            user=self.admin, name='Test Company',
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )

        company = services.get_company_service(user=self.admin, company_id=created.pk)

        self.assertEqual(company.name, 'Test Company')
        self.assertEqual(company.cnpj, '81585365000127')

    def test_get_company_from_another_user_raises(self):
        user = User.objects.create_user(
            email='user@test.com', password='Str@ngPassw8rd2026'
        )
        company = services.create_company_service(
            user=self.admin, name='Other',
            cnpj='81.585.365/0001-23', initial_balance=Decimal(0)
        )

        with self.assertRaises(Company.DoesNotExist):
            services.get_company_service(user=user, company_id=company.pk)

    # Test update

    def test_update_company_name(self):
        company = services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        updated = services.update_company_service(
            user=self.admin, company_id=company.pk, name='Test Updated Company'
        )
        self.assertEqual(updated.name, 'Test Updated Company')

    def test_update_company_cnpj(self):
        company = services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        updated = services.update_company_service(
            user=self.admin, company_id=company.pk, cnpj='81.585.365/0001-20'
        )
        self.assertEqual(updated.cnpj, '81585365000120')

    def test_update_another_company_with_existing_cnpj_raises(self):
        services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        company = services.create_company_service(
            user=self.admin, name='Test Company2', 
            cnpj='81.585.365/0001-28', initial_balance=Decimal(0)
        )
        with self.assertRaises(ValidationError):
            services.update_company_service(
                user=self.admin, company_id=company.pk, cnpj='81.585.365/0001-27'
            )

    def test_update_company_with_no_permission_raises(self):
        normal_user = User.objects.create_user(
            email='normaluser@email.com', password='Str@ngPassw8rd2026'
        )
        company = services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        with self.assertRaises(PermissionDenied):
            services.update_company_service(
                user=normal_user, company_id=company.pk, name='Test Company2'
            )

    # Test delete

    def test_delete_company_service(self):
        company = services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        services.delete_company_service(
            user=self.admin, company_id=company.pk
        )
        self.assertFalse(Company.objects.filter(pk=company.pk).exists())

    def test_delete_company_with_no_permission_raises(self):
        normal_user = User.objects.create_user(
            email='normaluser@email.com', password='Str@ngPassw8rd2026'
        )
        company = services.create_company_service(
            user=self.admin, name='Test Company', 
            cnpj='81.585.365/0001-27', initial_balance=Decimal(0)
        )
        with self.assertRaises(PermissionDenied):
            services.delete_company_service(
                user=normal_user, company_id=company.pk
            )

    def test_delete_non_existent_company(self):
        with self.assertRaises(Company.DoesNotExist):
            services.delete_company_service(
                user=self.admin, company_id=999
            )
