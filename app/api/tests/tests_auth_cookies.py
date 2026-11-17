from django.test import TestCase, override_settings

from api.endpoints.auth import ACCESS_COOKIE, REFRESH_COOKIE
from apps.users.models import User

PASSWORD = 'Str@ngPassw8rd2026'


@override_settings(DEBUG=False)  # production cookie flags (Secure)
class CookieSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='ana@test.com', password=PASSWORD)

    def login(self, email='ana@test.com', password=PASSWORD):
        return self.client.post('/api/auth/login', data={'email': email, 'password': password},
                                content_type='application/json')

    def test_login_sets_httponly_cookies_and_no_token_in_body(self):
        response = self.login(email=' ANA@test.com ')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        access, refresh = response.cookies[ACCESS_COOKIE], response.cookies[REFRESH_COOKIE]
        for cookie in (access, refresh):
            self.assertTrue(cookie['httponly'])
            self.assertTrue(cookie['secure'])
            self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(access['path'], '/api')
        self.assertEqual(refresh['path'], '/api/auth')  # never sent to the regular endpoints

    def test_cookie_authenticates_requests(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.login()
        response = self.client.get('/api/me')  # the test client keeps the cookies
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['email'], 'ana@test.com')

    def test_wrong_password_and_inactive_user(self):
        self.assertEqual(self.login(password='wrong').status_code, 401)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.login().status_code, 401)

    def test_refresh_issues_new_cookies(self):
        self.login()
        self.client.cookies.pop(ACCESS_COOKIE)  # access expired / gone
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        response = self.client.post('/api/auth/refresh')
        self.assertEqual(response.status_code, 204)
        self.assertIn(ACCESS_COOKIE, response.cookies)
        self.assertEqual(self.client.get('/api/me').status_code, 200)

    def test_refresh_without_or_with_bad_cookie(self):
        self.assertEqual(self.client.post('/api/auth/refresh').status_code, 401)
        self.client.cookies[REFRESH_COOKIE] = 'garbage'
        self.assertEqual(self.client.post('/api/auth/refresh').status_code, 401)

    def test_refresh_refused_for_deactivated_user(self):
        self.login()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post('/api/auth/refresh').status_code, 401)

    def test_logout_clears_cookies(self):
        self.login()
        response = self.client.post('/api/auth/logout')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies[ACCESS_COOKIE].value, '')
        self.assertEqual(response.cookies[REFRESH_COOKIE].value, '')
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_old_token_endpoints_are_gone(self):
        response = self.client.post('/api/token/pair', data={'email': 'ana@test.com', 'password': PASSWORD},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 404)
