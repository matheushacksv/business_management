from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.users.models import User


def create_user_service(email: str, password: str) -> User:
    validate_password(password, user=User(email=email))
    try:
        with transaction.atomic():
            return User.objects.create_user(email=email, password=password)
    except IntegrityError:
        raise ValidationError('user already exists')


def deactivate_user_service(requested_by: User, user_id: int) -> None:
    if not requested_by.is_superuser and requested_by.pk == user_id:
        raise PermissionDenied('no permission')

    user = get_object_or_404(User, pk=user_id)
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.save(update_fields=['is_active', 'deactivated_at'])
