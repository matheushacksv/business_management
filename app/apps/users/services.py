from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.companies.models import Company
from apps.users.models import Role, User


def _set_companies(user: User, company_ids: list[int]) -> None:
    companies = list(Company.objects.filter(pk__in=company_ids))
    if len(companies) != len(set(company_ids)):
        raise ValidationError('One or more companies do not exist')
    user.companies.set(companies)


def create_user_service(
    *, email: str, password: str, name: str = '', role: str = Role.MANAGER,
    company_ids: list[int] | None = None,
) -> User:
    validate_password(password, user=User(email=email))
    try:
        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password, name=name.strip(), role=role)
            if company_ids:
                _set_companies(user, company_ids)
            return user
    except IntegrityError:
        raise ValidationError('user already exists')


def list_users_service():
    return User.objects.prefetch_related('companies').order_by('email')


def get_user_service(*, user_id: int) -> User:
    return list_users_service().get(pk=user_id)


def update_user_service(*, requested_by: User, user_id: int, **fields) -> User:
    user = get_user_service(user_id=user_id)
    if user.pk == requested_by.pk and 'role' in fields and fields['role'] != user.role:
        raise PermissionDenied('You cannot change your own role')
    company_ids = fields.pop('company_ids', None)
    if 'name' in fields:
        fields['name'] = fields['name'].strip()
    for field, value in fields.items():
        setattr(user, field, value)
    with transaction.atomic():
        if fields:
            user.save(update_fields=list(fields))
        if company_ids is not None:
            _set_companies(user, company_ids)
    return user


def deactivate_user_service(*, requested_by: User, user_id: int) -> None:
    if requested_by.pk == user_id:
        raise PermissionDenied('You cannot deactivate yourself')
    user = User.objects.get(pk=user_id)
    user.is_active = False
    user.deactivated_at = timezone.now()
    user.save(update_fields=['is_active', 'deactivated_at'])
