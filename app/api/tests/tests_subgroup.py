from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Group, SubGroup, Transaction, TransactionType
from apps.users.models import Role, User


class SubGroupEndpointTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email='john@doe.com', password='Str@ngPassw8rd2026', role=Role.ADMIN)
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore
        self.rent = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)

    # Auth

    def test_requires_authentication(self):
        response = self.client.get('/api/subgroup')

        self.assertEqual(response.status_code, 401)

    # Create

    def test_create_subgroup(self):
        response = self.client.post(
            '/api/subgroup',
            data={'name': 'Sales', 'group': 'operating_revenue'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['name'], 'Sales')
        self.assertEqual(data['group'], 'operating_revenue')
        self.assertTrue(SubGroup.objects.filter(pk=data['id']).exists())

    def test_create_subgroup_with_invalid_group_returns_422(self):
        response = self.client.post(
            '/api/subgroup',
            data={'name': 'Sales', 'group': 'banana'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 422)

    def test_create_duplicated_subgroup_returns_400(self):
        response = self.client.post(
            '/api/subgroup',
            data={'name': 'Rent', 'group': 'fixed_costs'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 400)

    # List

    def test_list_subgroups(self):
        sales = services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)

        response = self.client.get('/api/subgroup', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual([s['id'] for s in response.json()], [self.rent.pk, sales.pk])

    def test_list_subgroups_filtered_by_group(self):
        services.create_subgroup_service(name='Sales', group=Group.OPERATING_REVENUE)

        response = self.client.get('/api/subgroup?group=fixed_costs', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s['id'] for s in response.json()], [self.rent.pk])

    def test_list_subgroups_with_invalid_group_returns_422(self):
        response = self.client.get('/api/subgroup?group=banana', headers=self.auth)

        self.assertEqual(response.status_code, 422)

    # Get

    def test_get_subgroup(self):
        response = self.client.get(f'/api/subgroup/{self.rent.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Rent')

    def test_get_non_existing_subgroup_returns_404(self):
        response = self.client.get('/api/subgroup/999999', headers=self.auth)

        self.assertEqual(response.status_code, 404)

    # Update

    def test_update_subgroup_name(self):
        response = self.client.patch(
            f'/api/subgroup/{self.rent.pk}',
            data={'name': 'Office Rent'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['name'], 'Office Rent')
        self.rent.refresh_from_db()
        self.assertEqual(self.rent.name, 'Office Rent')
        self.assertEqual(self.rent.group, Group.FIXED_COSTS)

    def test_update_subgroup_group(self):
        response = self.client.patch(
            f'/api/subgroup/{self.rent.pk}',
            data={'group': 'variable_costs'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 200)
        self.rent.refresh_from_db()
        self.assertEqual(self.rent.group, Group.VARIABLE_COSTS)
        self.assertEqual(self.rent.name, 'Rent')

    def test_update_subgroup_to_existing_name_returns_400(self):
        sales = services.create_subgroup_service(name='Salaries', group=Group.FIXED_COSTS)

        response = self.client.patch(
            f'/api/subgroup/{sales.pk}',
            data={'name': 'Rent'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 400)

    def test_update_non_existing_subgroup_returns_404(self):
        response = self.client.patch(
            '/api/subgroup/999999',
            data={'name': 'Rent'},
            content_type='application/json',
            headers=self.auth,
        )

        self.assertEqual(response.status_code, 404)

    # Delete

    def test_delete_subgroup(self):
        response = self.client.delete(f'/api/subgroup/{self.rent.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(SubGroup.objects.filter(pk=self.rent.pk).exists())

    def test_delete_non_existing_subgroup_returns_404(self):
        response = self.client.delete('/api/subgroup/999999', headers=self.auth)

        self.assertEqual(response.status_code, 404)

    def test_delete_subgroup_in_use_returns_400(self):
        company = Company.objects.create(name='Test Company', cnpj='81585365000127')
        Transaction.objects.create(
            company=company, subgroup=self.rent, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        response = self.client.delete(f'/api/subgroup/{self.rent.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(SubGroup.objects.filter(pk=self.rent.pk).exists())

    # Groups

    def test_list_groups(self):
        response = self.client.get('/api/groups', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0], {'value': 'operating_revenue', 'label': 'Receitas Operacionais'})
        self.assertEqual(len(response.json()), 5)
