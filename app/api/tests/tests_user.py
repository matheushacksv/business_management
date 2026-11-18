from django.test import TestCase
from ninja_jwt.tokens import AccessToken
from apps.users import services
from apps.users.models import User

class UserEndpointTests(TestCase):

    def setUp(self):
        admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(admin)}'}   #type:ignore

    # Test me

    def test_me_with_no_token_returns_401(self):
        response = self.client.get('/api/me')
        self.assertEqual(response.status_code, 401)

    def test_me_with_token_returns_user(self):
        user = services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')
        token = AccessToken.for_user(user)  #type: ignore
        response = self.client.get('/api/me', headers={'Authorization': f'Bearer {token}'}, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['email'], 'john@doe.com')

    # Test create

    def test_create_user_endpoint_with_no_matched_password(self):
        body = {
            'email': 'john@doe.com',
            'password': 'Str@ngPassw8rd2026',
            'repeat_password': '123'
        }
        response = self.client.post('/api/user', data=body, content_type='application/json', headers=self.auth)
        self.assertEqual(response.status_code, 422)

    def test_create_user_endpoint_with_matched_password(self):
        body = {
            'email': 'john@doe.com',
            'password': 'Str@ngPassw8rd2026',
            'repeat_password': 'Str@ngPassw8rd2026'
        }
        response = self.client.post('/api/user', data=body, content_type='application/json', headers=self.auth)
        self.assertEqual(response.status_code, 201)

    def test_create_user_endpoint_with_weak_password(self):
        body = {
            'email': 'john@doe.com',
            'password': '123',
            'repeat_password': '123'
        }
        response = self.client.post('/api/user', data=body, content_type='application/json', headers=self.auth)
        self.assertEqual(response.status_code, 400)

    def test_create_user_endpoint_with_repeated_email(self):
        services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')
        body = {
            'email': 'john@doe.com',
            'password': 'Str@ngPassw8rd2026',
            'repeat_password': 'Str@ngPassw8rd2026'
        }
        response = self.client.post('/api/user', data=body, content_type='application/json', headers=self.auth)
        self.assertEqual(response.status_code, 400)
        
    def test_create_user_endpoint_with_invalid_email(self):
        body = {
            'email': 'johndoe.com',
            'password': 'Str@ngPassw8rd2026',
            'repeat_password': 'Str@ngPassw8rd2026'
        }
        response = self.client.post('/api/user', data=body, content_type='application/json', headers=self.auth)
        self.assertEqual(response.status_code, 422)


class ChangePasswordTests(TestCase):

    def setUp(self):
        self.user = services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')
        self.auth = {'Authorization': f'Bearer {AccessToken.for_user(self.user)}'}  # type: ignore

    def post(self, current, new, repeat=None):
        body = {'current_password': current, 'new_password': new, 'repeat_password': repeat or new}
        return self.client.post('/api/me/password', data=body, content_type='application/json', headers=self.auth)

    def test_changes_password(self):
        self.assertEqual(self.post('Str@ngPassw8rd2026', 'Nov@Senha#Forte99').status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nov@Senha#Forte99'))

    def test_wrong_current_password(self):
        self.assertEqual(self.post('errada', 'Nov@Senha#Forte99').status_code, 400)

    def test_weak_new_password(self):
        self.assertEqual(self.post('Str@ngPassw8rd2026', '123').status_code, 400)

    def test_repeat_mismatch(self):
        self.assertEqual(self.post('Str@ngPassw8rd2026', 'Nov@Senha#Forte99', 'outra').status_code, 422)

    def test_requires_login(self):
        response = self.client.post('/api/me/password', data={}, content_type='application/json')
        self.assertEqual(response.status_code, 401)
