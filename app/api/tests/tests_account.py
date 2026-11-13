from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Account, Group, Transaction, TransactionType
from apps.users.models import Role, User


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class AccountEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        member = User.objects.create_user(email='member@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.company = Company.objects.create(name='Company A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='Company B', cnpj='11222333000181')
        member.companies.add(self.company)
        self.auth_admin = auth_for(self.admin)
        self.auth_member = auth_for(member)
        self.itau = services.create_account_service(
            user=self.admin, company_id=self.company.pk, name='Itaú'
        )
        self.other_account = services.create_account_service(
            user=self.admin, company_id=self.other_company.pk, name='Bradesco'
        )

    def post(self, data, auth):
        return self.client.post('/api/account', data=data, content_type='application/json', headers=auth)

    def patch(self, account_id, data, auth):
        return self.client.patch(
            f'/api/account/{account_id}', data=data, content_type='application/json', headers=auth
        )

    # Auth

    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/api/account').status_code, 401)

    # Create

    def test_member_creates_account_in_linked_company(self):
        response = self.post({'company_id': self.company.pk, 'name': 'Nubank'}, self.auth_member)

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['name'], 'Nubank')
        self.assertEqual(data['company'], self.company.pk)

    def test_member_creates_account_in_not_linked_company_returns_404(self):
        response = self.post({'company_id': self.other_company.pk, 'name': 'Nubank'}, self.auth_member)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Account.objects.filter(name='Nubank').exists())

    def test_create_duplicated_account_returns_400(self):
        response = self.post({'company_id': self.company.pk, 'name': 'Itaú'}, self.auth_admin)

        self.assertEqual(response.status_code, 400)

    def test_create_account_without_company_returns_422(self):
        self.assertEqual(self.post({'name': 'Nubank'}, self.auth_admin).status_code, 422)

    # List

    def test_admin_lists_all_accounts(self):
        response = self.client.get('/api/account', headers=self.auth_admin)

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [a['id'] for a in response.json()], [self.itau.pk, self.other_account.pk]
        )

    def test_member_lists_only_linked_accounts(self):
        response = self.client.get('/api/account', headers=self.auth_member)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([a['id'] for a in response.json()], [self.itau.pk])

    def test_list_accounts_filtered_by_company(self):
        response = self.client.get(
            f'/api/account?company_id={self.other_company.pk}', headers=self.auth_admin
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([a['id'] for a in response.json()], [self.other_account.pk])

    # Get

    def test_get_account(self):
        response = self.client.get(f'/api/account/{self.itau.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Itaú')

    def test_get_account_from_not_linked_company_returns_404(self):
        response = self.client.get(f'/api/account/{self.other_account.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 404)

    # Update

    def test_update_account_name(self):
        response = self.patch(self.itau.pk, {'name': 'Itaú CC'}, self.auth_member)

        self.assertEqual(response.status_code, 200)
        self.itau.refresh_from_db()
        self.assertEqual(self.itau.name, 'Itaú CC')

    def test_update_account_ignores_company_id(self):
        response = self.patch(
            self.itau.pk, {'name': 'Itaú CC', 'company_id': self.other_company.pk}, self.auth_admin
        )

        self.assertEqual(response.status_code, 200)
        self.itau.refresh_from_db()
        self.assertEqual(self.itau.company, self.company)

    def test_update_account_from_not_linked_company_returns_404(self):
        response = self.patch(self.other_account.pk, {'name': 'Hacked'}, self.auth_member)

        self.assertEqual(response.status_code, 404)
        self.other_account.refresh_from_db()
        self.assertEqual(self.other_account.name, 'Bradesco')

    def test_update_account_to_existing_name_returns_400(self):
        nubank = services.create_account_service(user=self.admin, company_id=self.company.pk, name='Nubank')

        response = self.patch(nubank.pk, {'name': 'Itaú'}, self.auth_admin)

        self.assertEqual(response.status_code, 400)

    # Delete

    def test_delete_account(self):
        response = self.client.delete(f'/api/account/{self.itau.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Account.objects.filter(pk=self.itau.pk).exists())

    def test_delete_account_from_not_linked_company_returns_404(self):
        response = self.client.delete(f'/api/account/{self.other_account.pk}', headers=self.auth_member)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Account.objects.filter(pk=self.other_account.pk).exists())

    def test_delete_account_in_use_returns_400(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        Transaction.objects.create(
            company=self.company, account=self.itau, subgroup=subgroup, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        response = self.client.delete(f'/api/account/{self.itau.pk}', headers=self.auth_admin)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Account.objects.filter(pk=self.itau.pk).exists())
