import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, QuerySet
from django.shortcuts import get_object_or_404

from apps.companies.models import Company
from apps.users.models import User
from apps.users.permissions import CHANGE, CREATE, DELETE, check_permission


def normalize_cnpj(cnpj: str) -> str:
    return re.sub(r'[.\-/\s]', '', cnpj).upper()


def create_company_service(
    user: User, name: str, cnpj: str, initial_balance: Decimal, tax_rate: Decimal = Decimal('10'),
    pipedrive_label: str = '',
) -> Company:
    check_permission(user, 'companies', CREATE)
    cnpj = normalize_cnpj(cnpj)

    try:
        with transaction.atomic():
            return Company.objects.create(
                name=name.strip(), cnpj=cnpj, initial_balance=initial_balance, tax_rate=tax_rate,
                pipedrive_label=pipedrive_label.strip(),
            )
    except IntegrityError:
        raise ValidationError('Company with this CNPJ already exists')


def list_companies_service(user: User) -> QuerySet[Company]:
    if user.is_admin:
        return Company.objects.all()
    return user.companies.all()


def get_company_service(user: User, company_id: int) -> Company:
    return list_companies_service(user=user).get(pk=company_id)


def update_company_service(user: User, company_id: int, **fields) -> Company:
    check_permission(user, 'companies', CHANGE)
    company = get_object_or_404(Company, pk=company_id)
    if 'name' in fields:
        fields['name'] = fields['name'].strip()
    if 'cnpj' in fields:
        fields['cnpj'] = normalize_cnpj(fields['cnpj'])
    if 'pipedrive_label' in fields:
        fields['pipedrive_label'] = (fields['pipedrive_label'] or '').strip()

    for field, value in fields.items():
        setattr(company, field, value)

    try:
        with transaction.atomic():
            company.save(update_fields=list(fields))
    except IntegrityError:
        raise ValidationError('Company with this CNPJ already exists')
    return company


def delete_company_service(user: User, company_id: int) -> None:
    check_permission(user, 'companies', DELETE)
    try:
        Company.objects.get(pk=company_id).delete()
    except ProtectedError:
        raise ValidationError('Company has linked records and cannot be deleted')
    except Company.DoesNotExist:
        raise Company.DoesNotExist