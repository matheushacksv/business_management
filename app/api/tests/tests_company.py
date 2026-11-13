from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies import services
from apps.users.models import User


class CompanyEndpointTests(TestCase):
    def setUp(self):
        admin = User.objects.create_superuser(
            email='admin@test.com', password='Str@ngPassw8rd2026'
        )
        normal = User.objects.create_user(
            email='john@doe.com', password='Str@ngPassw8rd2026'
        )
        company = services.create_company_service(
            user=admin,
            name='Test Company',
            cnpj='81.585.365/0001-27',
            initial_balance=Decimal(0),
        )
        self.admin_user = admin
        self.test_company = company
        self.normal_user = normal
        self.auth_admin = {'Authorization': f'Bearer {AccessToken.for_user(admin)}'}  # type:ignore
        self.auth_normal_user = {
            'Authorization': f'Bearer {AccessToken.for_user(normal)}'   # type:ignore
        }  

    # Create tests

    def test_create_company_endpoint(self):
        body = {
            'name': 'Test Company',
            'cnpj': '81.585.365/0001-28',
            'initial_balance': 0,
        }
        response = self.client.post(
            '/api/company',
            data=body,
            content_type='application/json',
            headers=self.auth_admin,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['name'], 'Test Company')
        self.assertEqual(response.json()['cnpj'], '81585365000128')

    def test_create_company_with_no_permission(self):
        body = {
            'name': 'Test Company',
            'cnpj': '81.585.365/0001-22',
            'initial_balance': 0,
        }
        response = self.client.post(
            '/api/company',
            data=body,
            content_type='application/json',
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 403)

    def test_create_company_missing_fields(self):
        body = {'cnpj': '81.585.365/0001-29', 'initial_balance': 0}
        response = self.client.post(
            '/api/company',
            data=body,
            content_type='application/json',
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 422)

    def test_create_company_that_already_exists(self):
        body = {
            'name': 'Test Company',
            'cnpj': '81.585.365/0001-27',
            'initial_balance': 0,
        }
        response = self.client.post(
            '/api/company',
            data=body,
            content_type='application/json',
            headers=self.auth_admin,
        )
        self.assertEqual(response.status_code, 400)

    # Test list/get

    def test_list_companies(self):
        company1 = services.create_company_service(
            user=self.admin_user,
            name='Test Company',
            cnpj='81.585.365/0001-10',
            initial_balance=Decimal(0),
        )
        company2 = services.create_company_service(
            user=self.admin_user,
            name='Test Company2',
            cnpj='81.585.365/0001-11',
            initial_balance=Decimal(0),
        )
        response = self.client.get('/api/company', headers=self.auth_admin)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertCountEqual(
            [(c['name'], c['cnpj']) for c in data],
            [
                (self.test_company.name, self.test_company.cnpj),
                (company1.name, company1.cnpj),
                (company2.name, company2.cnpj),
            ],
        )

    def test_get_company(self):
        response = self.client.get(
            f'/api/company/{self.test_company.pk}', headers=self.auth_admin
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], self.test_company.name)
        self.assertEqual(response.json()['cnpj'], self.test_company.cnpj)

    def test_get_company_without_permission(self):
        response = self.client.get(
            f'/api/company/{self.test_company.pk}',
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 404)

    def test_get_company_linked_to_user(self):
        self.normal_user.companies.add(self.test_company)
        response = self.client.get(
            f'/api/company/{self.test_company.pk}', headers=self.auth_normal_user
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], self.test_company.pk)

    # update tests

    def test_update_company(self):
        body = {'name': 'Test Updated Company', 'cnpj': '81.585.365/0001-20'}
        response = self.client.patch(
            f'/api/company/{self.test_company.pk}',
            content_type='application/json',
            data=body,
            headers=self.auth_admin,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Test Updated Company')
        self.assertEqual(response.json()['cnpj'], '81585365000120')

    def test_update_company_without_permission(self):
        body = {'name': 'Test Updated Company', 'cnpj': '81.585.365/0001-20'}
        response = self.client.patch(
            f'/api/company/{self.test_company.pk}',
            content_type='application/json',
            data=body,
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 403)

    def test_update_company_with_duplicated_cnpj(self):
        other = services.create_company_service(
            user=self.admin_user,
            name='Other Company',
            cnpj='81.585.365/0001-28',
            initial_balance=Decimal(0),
        )
        body = {'name': 'Test Updated Company', 'cnpj': self.test_company.cnpj}
        response = self.client.patch(
            f'/api/company/{other.pk}',
            data=body,
            content_type='application/json',
            headers=self.auth_admin,
        )
        self.assertEqual(response.status_code, 400)

    def test_update_non_existent_company(self):
        body = {'name': 'Test Updated Company', 'cnpj': '81.585.365/0001-27'}
        response = self.client.patch(
            '/api/company/999',
            content_type='application/json',
            headers=self.auth_admin,
            data=body,
        )
        self.assertEqual(response.status_code, 404)

    # delete tests

    def test_delete_company(self):
        company = services.create_company_service(
            user=self.admin_user,
            name='Company to be deleted',
            cnpj='81.585.365/0001-19',
            initial_balance=Decimal(0),
        )
        response = self.client.delete(
            f'/api/company/{company.pk}',
            headers=self.auth_admin,
        )
        self.assertEqual(response.status_code, 204)

    def test_delete_company_without_permission(self):
        response = self.client.delete(
            f'/api/company/{self.test_company.pk}',
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 403)

    def test_delete_non_existing_company(self):
        response = self.client.delete(
            '/api/company/999',
            headers=self.auth_normal_user,
        )
        self.assertEqual(response.status_code, 403)
