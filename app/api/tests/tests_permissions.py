from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Account, Group, TransactionType
from apps.users.models import Role, User
from apps.users.permissions import has_permission, permissions_for


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


class PermissionMatrixTest(TestCase):
    """Every role x every module/action, through the real endpoints."""

    def setUp(self):
        self.admin = User.objects.create_superuser(email='root@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.contact = services.create_contact_service(name='Landlord')
        self.account = Account.objects.create(company=self.company, name='Itaú')
        self.tx = services.create_transaction_service(
            user=self.admin, company_id=self.company.pk, subgroup_id=self.subgroup.pk,
            date=date(2026, 1, 10), amount=Decimal('100'), type=TransactionType.OUTFLOW,
        )
        self.users = {}
        for role in Role:
            user = User.objects.create_user(email=f'{role}@test.com', password='Str@ngPassw8rd2026', role=role)
            user.companies.add(self.company)
            self.users[role] = user

    def requests(self):
        c, s, ct, a, t = self.company.pk, self.subgroup.pk, self.contact.pk, self.account.pk, self.tx.pk
        return {
            ('companies', 'view'): ('get', '/api/company', None),
            ('companies', 'create'): ('post', '/api/company', {'name': 'X', 'cnpj': '11222333000181', 'initial_balance': 0}),
            ('companies', 'change'): ('patch', f'/api/company/{c}', {'name': 'Y'}),
            ('subgroups', 'view'): ('get', '/api/subgroup', None),
            ('subgroups', 'create'): ('post', '/api/subgroup', {'name': 'New', 'group': 'fixed_costs'}),
            ('subgroups', 'change'): ('patch', f'/api/subgroup/{s}', {'name': 'Rent 2'}),
            ('subgroups', 'delete'): ('delete', '/api/subgroup/999999', None),
            ('contacts', 'view'): ('get', '/api/contact', None),
            ('contacts', 'create'): ('post', '/api/contact', {'name': 'New'}),
            ('contacts', 'change'): ('patch', f'/api/contact/{ct}', {'phone': '1'}),
            ('contacts', 'delete'): ('delete', '/api/contact/999999', None),
            ('accounts', 'view'): ('get', '/api/account', None),
            ('accounts', 'create'): ('post', '/api/account', {'company_id': c, 'name': 'New'}),
            ('accounts', 'change'): ('patch', f'/api/account/{a}', {'name': 'Itaú 2'}),
            ('accounts', 'delete'): ('delete', '/api/account/999999', None),
            ('transactions', 'view'): ('get', '/api/transaction', None),
            ('transactions', 'create'): ('post', '/api/transaction', {
                'company_id': c, 'subgroup_id': s, 'date': '2026-01-01', 'amount': '1', 'type': 'outflow'}),
            ('transactions', 'change'): ('patch', f'/api/transaction/{t}', {'notes': 'x'}),
            ('transactions', 'delete'): ('delete', '/api/transaction/999999', None),
            ('reports', 'view'): ('get', '/api/reports/dre?year=2026', None),
            ('sales', 'view'): ('get', '/api/sale', None),
            ('sales', 'create'): ('post', '/api/sale', {'company_id': c, 'date': '2026-01-01', 'amount': '10'}),
            ('sales', 'change'): ('patch', '/api/sale/999999', {'notes': 'x'}),
            ('sales', 'delete'): ('delete', '/api/sale/999999', None),
            ('dunning', 'view'): ('get', '/api/dunning/stage', None),
            ('dunning', 'change'): ('patch', '/api/dunning/card/999999', {}),
            ('users', 'view'): ('get', '/api/user', None),
            ('users', 'change'): ('patch', f'/api/user/{self.admin.pk}', {'name': 'Root'}),
        }

    def test_endpoints_follow_the_matrix(self):
        for role, user in self.users.items():
            auth = auth_for(user)
            for (module, action), (method, url, body) in self.requests().items():
                with self.subTest(role=role, module=module, action=action):
                    kwargs = {'headers': auth}
                    if body is not None:
                        kwargs.update(data=body, content_type='application/json')
                    response = getattr(self.client, method)(url, **kwargs)
                    allowed = has_permission(user, module, action)
                    if allowed:
                        self.assertNotEqual(response.status_code, 403, response.content)
                    else:
                        self.assertEqual(response.status_code, 403, response.content)

    def test_expected_matrix(self):
        expected = {
            Role.ADMIN: {'users': 'vcud', 'companies': 'vcud', 'subgroups': 'vcud', 'contacts': 'vcud',
                         'accounts': 'vcud', 'transactions': 'vcud', 'reports': 'vcud', 'sales': 'vcud', 'legal': 'vcud', 'dunning': 'vcud', 'investments': 'vcud'},
            Role.FINANCE: {'users': '', 'companies': 'v', 'subgroups': 'v', 'contacts': 'vcud',
                           'accounts': 'vcud', 'transactions': 'vcud', 'reports': 'v', 'sales': 'vcud', 'legal': 'vcud', 'dunning': 'vcud', 'investments': 'vcud'},
            Role.ACCOUNTANT: {'users': '', 'companies': 'v', 'subgroups': 'v', 'contacts': 'v',
                              'accounts': 'v', 'transactions': 'v', 'reports': 'v', 'sales': 'v', 'legal': '', 'dunning': '', 'investments': 'v'},
            Role.MANAGER: {'users': '', 'companies': 'v', 'subgroups': 'v', 'contacts': '',
                           'accounts': '', 'transactions': '', 'reports': 'v', 'sales': 'v', 'legal': 'v', 'dunning': 'v', 'investments': 'v'},
            Role.LEGAL: {'users': '', 'companies': 'v', 'subgroups': '', 'contacts': 'v',
                         'accounts': '', 'transactions': '', 'reports': '', 'sales': 'v', 'legal': 'vcud', 'dunning': '', 'investments': ''},
        }
        letters = {'view': 'v', 'create': 'c', 'change': 'u', 'delete': 'd'}
        for role, modules in expected.items():
            with self.subTest(role=role):
                actual = {m: ''.join(sorted((letters[a] for a in acts), key='vcud'.index))
                          for m, acts in permissions_for(self.users[role]).items()}
                self.assertEqual(actual, {m: ''.join(sorted(v, key='vcud'.index)) for m, v in modules.items()})

    def test_admin_role_sees_all_companies(self):
        other = Company.objects.create(name='B', cnpj='11222333000181')

        response = self.client.get('/api/company', headers=auth_for(self.users[Role.ADMIN]))

        self.assertCountEqual([c['id'] for c in response.json()], [self.company.pk, other.pk])

    def test_inactive_user_has_no_permission(self):
        user = self.users[Role.FINANCE]
        user.is_active = False

        self.assertFalse(has_permission(user, 'transactions', 'view'))


class UserManagementEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email='admin@test.com', password='Str@ngPassw8rd2026', role=Role.ADMIN)
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other = Company.objects.create(name='B', cnpj='11222333000181')
        self.auth_admin = auth_for(self.admin)
        self.auth_finance = auth_for(self.finance)

    def patch(self, user_id, data, auth=None):
        return self.client.patch(f'/api/user/{user_id}', data=data, content_type='application/json',
                                 headers=auth or self.auth_admin)

    def test_me_returns_role_and_permissions(self):
        response = self.client.get('/api/me', headers=self.auth_finance)

        data = response.json()
        self.assertEqual(data['role'], 'finance')
        self.assertFalse(data['is_admin'])
        self.assertEqual(data['permissions']['transactions'], ['change', 'create', 'delete', 'view'])
        self.assertEqual(data['permissions']['users'], [])

    def test_create_user_with_role_and_companies(self):
        response = self.client.post('/api/user', data={
            'email': 'new@test.com', 'password': 'Str@ngPassw8rd2026', 'repeat_password': 'Str@ngPassw8rd2026',
            'name': ' New ', 'role': 'accountant', 'company_ids': [self.company.pk],
        }, content_type='application/json', headers=self.auth_admin)

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['role'], 'accountant')
        self.assertEqual(data['name'], 'New')
        self.assertEqual(data['company_ids'], [self.company.pk])

    def test_create_user_defaults_to_manager(self):
        response = self.client.post('/api/user', data={
            'email': 'new@test.com', 'password': 'Str@ngPassw8rd2026', 'repeat_password': 'Str@ngPassw8rd2026',
        }, content_type='application/json', headers=self.auth_admin)

        self.assertEqual(response.json()['role'], 'manager')

    def test_create_user_with_non_existing_company_returns_400(self):
        response = self.client.post('/api/user', data={
            'email': 'new@test.com', 'password': 'Str@ngPassw8rd2026', 'repeat_password': 'Str@ngPassw8rd2026',
            'company_ids': [999999],
        }, content_type='application/json', headers=self.auth_admin)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='new@test.com').exists())

    def test_non_admin_cannot_create_user(self):
        response = self.client.post('/api/user', data={
            'email': 'new@test.com', 'password': 'Str@ngPassw8rd2026', 'repeat_password': 'Str@ngPassw8rd2026',
            'role': 'admin',
        }, content_type='application/json', headers=self.auth_finance)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='new@test.com').exists())

    def test_list_and_get_users(self):
        response = self.client.get('/api/user', headers=self.auth_admin)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([u['email'] for u in response.json()], ['admin@test.com', 'fin@test.com'])
        self.assertEqual(self.client.get(f'/api/user/{self.finance.pk}', headers=self.auth_admin).status_code, 200)
        self.assertEqual(self.client.get('/api/user/999999', headers=self.auth_admin).status_code, 404)

    def test_update_role_and_companies(self):
        self.finance.companies.add(self.other)

        response = self.patch(self.finance.pk, {'role': 'legal', 'company_ids': [self.company.pk]})

        self.assertEqual(response.status_code, 200)
        self.finance.refresh_from_db()
        self.assertEqual(self.finance.role, Role.LEGAL)
        self.assertEqual(list(self.finance.companies.all()), [self.company])

    def test_update_companies_to_empty(self):
        self.finance.companies.add(self.company)

        self.patch(self.finance.pk, {'company_ids': []})

        self.assertFalse(self.finance.companies.exists())

    def test_admin_cannot_change_own_role(self):
        response = self.patch(self.admin.pk, {'role': 'finance'})

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)

    def test_admin_can_change_own_name(self):
        self.assertEqual(self.patch(self.admin.pk, {'name': 'Boss', 'role': 'admin'}).status_code, 200)

    def test_non_admin_cannot_change_own_role(self):
        response = self.patch(self.finance.pk, {'role': 'admin'}, self.auth_finance)

        self.assertEqual(response.status_code, 403)
        self.finance.refresh_from_db()
        self.assertEqual(self.finance.role, Role.FINANCE)

    def test_deactivate_user(self):
        response = self.client.post(f'/api/user/deactivate/{self.finance.pk}', headers=self.auth_admin)

        self.assertEqual(response.status_code, 204)
        self.finance.refresh_from_db()
        self.assertFalse(self.finance.is_active)
        self.assertIsNotNone(self.finance.deactivated_at)

    def test_non_admin_cannot_deactivate_others(self):
        # Regression: the old check let any user deactivate anyone but themselves
        response = self.client.post(f'/api/user/deactivate/{self.admin.pk}', headers=self.auth_finance)

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_cannot_deactivate_self(self):
        response = self.client.post(f'/api/user/deactivate/{self.admin.pk}', headers=self.auth_admin)

        self.assertEqual(response.status_code, 403)

    def test_deactivate_non_existing_user_returns_404(self):
        self.assertEqual(self.client.post('/api/user/deactivate/999999', headers=self.auth_admin).status_code, 404)

    def test_deactivated_user_loses_access(self):
        self.client.post(f'/api/user/deactivate/{self.finance.pk}', headers=self.auth_admin)

        response = self.client.get('/api/transaction', headers=self.auth_finance)

        self.assertEqual(response.status_code, 401)
