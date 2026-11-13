from __future__ import annotations

from typing import ClassVar
import pghistory
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

class Role(models.TextChoices):
    ADMIN = 'admin', 'Administrador'
    FINANCE = 'finance', 'Financeiro'
    LEGAL = 'legal', 'Jurídico'
    ACCOUNTANT = 'accountant', 'Contador'
    MANAGER = 'manager', 'Gestor'


class UserManager(BaseUserManager):
    def create_user(self, email: str, password: str, **extra_fields) -> User:
        if not email:
            raise ValueError('E-mail is required')
        email = email.lower().strip()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self.db)
        return user

    def create_superuser(self, email: str, password: str, **extra_fields) -> User:
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_staff', True)
        return self.create_user(email=email, password=password, **extra_fields)

# Role/activation changes are audited; credentials never reach the history tables
@pghistory.track(
    pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent(),
    exclude=['password', 'last_login'],
)
class User(AbstractBaseUser, PermissionsMixin):
    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MANAGER)
    companies = models.ManyToManyField('companies.Company', blank=True, related_name='users')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects: ClassVar[UserManager] = UserManager()

    def __str__(self):
        return self.email

    @property
    def is_admin(self) -> bool:
        return self.is_superuser or self.role == Role.ADMIN
    
