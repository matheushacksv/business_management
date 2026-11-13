from datetime import date
from decimal import Decimal

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Contact, Group, Transaction, TransactionType
from apps.users.models import User


class ContactEndpointTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email='john@doe.com', password='Str@ngPassw8rd2026')
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore
        self.acme = services.create_contact_service(
            name='Acme', company_name='Acme Ltda', document='81585365000127'
        )

    def post(self, data):
        return self.client.post(
            '/api/contact', data=data, content_type='application/json', headers=self.auth
        )

    def patch(self, contact_id, data):
        return self.client.patch(
            f'/api/contact/{contact_id}', data=data, content_type='application/json', headers=self.auth
        )

    # Auth

    def test_requires_authentication(self):
        self.assertEqual(self.client.get('/api/contact').status_code, 401)

    # Create

    def test_create_contact_with_name_only(self):
        response = self.post({'name': 'John Doe'})

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['name'], 'John Doe')
        self.assertEqual(data['document'], '')
        self.assertTrue(Contact.objects.filter(pk=data['id']).exists())

    def test_create_contact_full(self):
        response = self.post({
            'name': 'Mary', 'company_name': 'Mary Co', 'document': '11.222.333/0001-81',
            'email': 'Mary@Co.com', 'phone': '11 98888-7777',
        })

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['document'], '11222333000181')
        self.assertEqual(data['email'], 'mary@co.com')

    def test_create_contact_without_name_returns_422(self):
        self.assertEqual(self.post({'company_name': 'No name'}).status_code, 422)

    def test_create_contact_with_invalid_email_returns_422(self):
        self.assertEqual(self.post({'name': 'John', 'email': 'not-an-email'}).status_code, 422)

    def test_create_duplicated_document_returns_400(self):
        response = self.post({'name': 'Acme 2', 'document': '81.585.365/0001-27'})

        self.assertEqual(response.status_code, 400)

    # List

    def test_list_contacts(self):
        mary = services.create_contact_service(name='Mary')

        response = self.client.get('/api/contact', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual([c['id'] for c in response.json()], [self.acme.pk, mary.pk])

    def test_search_contacts(self):
        services.create_contact_service(name='Mary')

        response = self.client.get('/api/contact?search=acme', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([c['id'] for c in response.json()], [self.acme.pk])

    # Get

    def test_get_contact(self):
        response = self.client.get(f'/api/contact/{self.acme.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['company_name'], 'Acme Ltda')

    def test_get_non_existing_contact_returns_404(self):
        self.assertEqual(self.client.get('/api/contact/999999', headers=self.auth).status_code, 404)

    # Update

    def test_update_contact_keeps_other_fields(self):
        response = self.patch(self.acme.pk, {'phone': '11 97777-6666'})

        self.assertEqual(response.status_code, 200)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.phone, '11 97777-6666')
        self.assertEqual(self.acme.name, 'Acme')
        self.assertEqual(self.acme.document, '81585365000127')

    def test_update_contact_with_null_does_not_change_field(self):
        response = self.patch(self.acme.pk, {'name': None})

        self.assertEqual(response.status_code, 200)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.name, 'Acme')

    def test_update_contact_clear_document(self):
        response = self.patch(self.acme.pk, {'document': ''})

        self.assertEqual(response.status_code, 200)
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.document, '')

    def test_update_contact_to_existing_document_returns_400(self):
        other = services.create_contact_service(name='Other', document='11222333000181')

        response = self.patch(other.pk, {'document': '81585365000127'})

        self.assertEqual(response.status_code, 400)

    def test_update_contact_with_invalid_email_returns_422(self):
        self.assertEqual(self.patch(self.acme.pk, {'email': 'nope'}).status_code, 422)

    def test_update_non_existing_contact_returns_404(self):
        self.assertEqual(self.patch(999999, {'name': 'X'}).status_code, 404)

    # Delete

    def test_delete_contact(self):
        response = self.client.delete(f'/api/contact/{self.acme.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Contact.objects.filter(pk=self.acme.pk).exists())

    def test_delete_non_existing_contact_returns_404(self):
        self.assertEqual(self.client.delete('/api/contact/999999', headers=self.auth).status_code, 404)

    def test_delete_contact_in_use_returns_400(self):
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        company = Company.objects.create(name='Test Company', cnpj='81585365000127')
        Transaction.objects.create(
            company=company, subgroup=subgroup, contact=self.acme, date=date(2026, 1, 10),
            amount=Decimal('100.00'), type=TransactionType.OUTFLOW,
        )

        response = self.client.delete(f'/api/contact/{self.acme.pk}', headers=self.auth)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Contact.objects.filter(pk=self.acme.pk).exists())
