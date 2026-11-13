from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.users import services

class CreateUserServiceTests(TestCase):

    # Test create
    
    def test_create_user_with_hashed_password(self):
        user = services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')

        self.assertEqual(user.email, 'john@doe.com')
        self.assertNotEqual(user.password, 'Str@ngPassw8rd2026')
        self.assertTrue(user.check_password('Str@ngPassw8rd2026'))

    def test_duplicate_email_raise_validation_error(self):
        services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')

        with self.assertRaises(ValidationError):
            services.create_user_service(email='john@doe.com', password='Str@ngPassw8rd2026')

    def test_create_user_with_short_password(self):
        with self.assertRaises(ValidationError):
            services.create_user_service(email='john@doe.com', password='123')

    def test_create_user_with_password_like_email(self):
        with self.assertRaises(ValidationError):
            services.create_user_service(email='john@doe.com', password='john.doe')

    def test_create_user_with_upper_email(self):
        user = services.create_user_service(email='   JOHN@doe.com   ', password='Str@ngPassw8rd2026')
        self.assertEqual(user.email, 'john@doe.com')
