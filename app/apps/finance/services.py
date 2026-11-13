import pghistory
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, Q

from apps.companies.services import list_companies_service, normalize_cnpj
from apps.finance.models import Account, Contact, Group, SubGroup, Transaction, TransactionStatus
from apps.users.models import User

# Subgroups services


def create_subgroup_service(name: str, group: Group) -> SubGroup:
    try:
        with transaction.atomic():
            return SubGroup.objects.create(name=name.strip(), group=group)
    except IntegrityError:
        raise ValidationError('Subgroup already exists in this group')


def list_subgroups_service(group: Group | None = None):
    qs = SubGroup.objects.all()
    return qs.filter(group=group) if group else qs


def get_subgroup_service(subgroup_id: int) -> SubGroup:
    return SubGroup.objects.get(pk=subgroup_id)


def update_subgroup_service(subgroup_id: int, **fields) -> SubGroup:
    try:
        subgroup = SubGroup.objects.get(pk=subgroup_id)
    except SubGroup.DoesNotExist:
        raise SubGroup.DoesNotExist
    if 'name' in fields:
        subgroup.name = fields['name'].strip()
    if 'group' in fields:
        subgroup.group = fields['group']

    try:
        with transaction.atomic():
            subgroup.save(update_fields=list(fields))
    except IntegrityError:
        raise ValidationError('Subgroup with this name already exists')
    return subgroup


def delete_subgroup_service(subgroup_id: int):
    subgroup = SubGroup.objects.get(pk=subgroup_id)
    try:
        subgroup.delete()
    except ProtectedError:
        raise ValidationError('Subgroup is in use by transactions')


# Contacts services


def create_contact_service(
    *,
    name: str,
    company_name: str = '',
    document: str = '',
    email: str = '',
    phone: str = '',
) -> Contact:
    try:
        with transaction.atomic():
            return Contact.objects.create(
                name=name.strip(),
                company_name=company_name.strip(),
                document=normalize_cnpj(document),
                email=email.strip().lower(),
                phone=phone.strip(),
            )
    except IntegrityError:
        raise ValidationError('Contact with this document already exists')


def list_contacts_service(*, search: str | None = None):
    qs = Contact.objects.all()
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(company_name__icontains=search)
            | Q(document__icontains=search)
        )
    return qs


def get_contact_service(*, contact_id: int) -> Contact:
    return Contact.objects.get(pk=contact_id)


def update_contact_service(*, contact_id: int, **fields) -> Contact:
    contact = Contact.objects.get(pk=contact_id)
    if 'document' in fields:
        fields['document'] = normalize_cnpj(fields['document'])
    if 'email' in fields:
        fields['email'] = fields['email'].strip().lower()
    for field, value in fields.items():
        setattr(contact, field, value.strip() if isinstance(value, str) else value)
    try:
        with transaction.atomic():
            contact.save(update_fields=list(fields))
    except IntegrityError:
        raise ValidationError('Contact with this document already exists')
    return contact


def delete_contact_service(*, contact_id: int) -> None:
    contact = Contact.objects.get(pk=contact_id)
    try:
        contact.delete()
    except ProtectedError:
        raise ValidationError('Contact is in use by transactions')


# Accounts services

def _accounts_for(user: User):
    return Account.objects.filter(company__in=list_companies_service(user=user))


def create_account_service(*, user: User, company_id: int, name: str) -> Account:
    company = list_companies_service(user=user).get(pk=company_id)
    try:
        with transaction.atomic():
            return Account.objects.create(company=company, name=name.strip())
    except IntegrityError:
        raise ValidationError('Account with this name already exists in this company')


def list_accounts_service(*, user: User, company_id: int | None = None):
    qs = _accounts_for(user).select_related('company')
    return qs.filter(company_id=company_id) if company_id else qs


def get_account_service(*, user: User, account_id: int) -> Account:
    return _accounts_for(user).get(pk=account_id)


def update_account_service(*, user: User, account_id: int, name: str) -> Account:
    account = get_account_service(user=user, account_id=account_id)
    account.name = name.strip()
    try:
        with transaction.atomic():
            account.save(update_fields=['name', 'updated_at'])
    except IntegrityError:
        raise ValidationError('Account with this name already exists in this company')
    return account


def delete_account_service(*, user: User, account_id: int) -> None:
    account = get_account_service(user=user, account_id=account_id)
    try:
        account.delete()
    except ProtectedError:
        raise ValidationError('Account is in use by transactions')


# Transactions services
# Access follows the company, like accounts. Writes run inside pghistory.context
# so every audit event records who made the change.

def _transactions_for(user: User):
    return Transaction.objects.filter(company__in=list_companies_service(user=user))


def _check_refs(*, company_id: int, subgroup_id=None, account_id=None, contact_id=None) -> None:
    # Body references that don't exist are a bad request (400), not a missing resource (404)
    if subgroup_id is not None and not SubGroup.objects.filter(pk=subgroup_id).exists():
        raise ValidationError('Subgroup does not exist')
    if contact_id is not None and not Contact.objects.filter(pk=contact_id).exists():
        raise ValidationError('Contact does not exist')
    if account_id is not None and not Account.objects.filter(pk=account_id, company_id=company_id).exists():
        raise ValidationError('Account does not exist in this company')


def create_transaction_service(
    *, user: User, company_id: int, subgroup_id: int, date, amount, type: str,
    status: str = TransactionStatus.PLANNED, account_id: int | None = None,
    contact_id: int | None = None, reference: str = '', notes: str = '',
) -> Transaction:
    company = list_companies_service(user=user).get(pk=company_id)
    _check_refs(company_id=company.pk, subgroup_id=subgroup_id, account_id=account_id, contact_id=contact_id)
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            return Transaction.objects.create(
                company=company, subgroup_id=subgroup_id, account_id=account_id,
                contact_id=contact_id, date=date, amount=amount, type=type, status=status,
                reference=reference.strip(), notes=notes.strip(),
            )
    except IntegrityError:
        raise ValidationError('Invalid transaction')


TRANSACTION_ORDERING = ('date', '-date', 'amount', '-amount', 'created_at', '-created_at')


def list_transactions_service(
    *, user: User, company_id=None, date_from=None, date_to=None, status=None, type=None,
    group=None, subgroup_id=None, account_id=None, contact_id=None,
    amount_min=None, amount_max=None, search: str | None = None, ordering: str | None = None,
):
    # Every filter is optional; list values become `__in` lookups (multi-select)
    filters = {
        'company_id': company_id, 'date__gte': date_from, 'date__lte': date_to,
        'status': status, 'type': type, 'subgroup__group': group, 'subgroup_id': subgroup_id,
        'account_id': account_id, 'contact_id': contact_id,
        'amount__gte': amount_min, 'amount__lte': amount_max,
    }
    lookups = {}
    for key, value in filters.items():
        if value is None or value == []:
            continue
        if isinstance(value, (list, tuple, set)):
            lookups[f'{key}__in'] = value
        else:
            lookups[key] = value

    qs = _transactions_for(user).filter(**lookups)
    if search:
        # ponytail: icontains = full scan; add pg_trgm GIN indexes once EXPLAIN on real data asks for it
        qs = qs.filter(
            Q(reference__icontains=search)
            | Q(notes__icontains=search)
            | Q(subgroup__name__icontains=search)
            | Q(contact__name__icontains=search)
            | Q(contact__company_name__icontains=search)
        )
    if ordering:
        if ordering not in TRANSACTION_ORDERING:
            raise ValidationError(f'Invalid ordering: {ordering}')
        qs = qs.order_by(ordering, '-id')  # -id keeps pagination stable on ties
    return qs.select_related('company', 'subgroup', 'account', 'contact')


def get_transaction_service(*, user: User, transaction_id: int) -> Transaction:
    return _transactions_for(user).select_related('subgroup').get(pk=transaction_id)


def update_transaction_service(*, user: User, transaction_id: int, **fields) -> Transaction:
    # ponytail: company is immutable; to move a transaction, delete and recreate it
    tx = get_transaction_service(user=user, transaction_id=transaction_id)
    _check_refs(
        company_id=tx.company_id,  # type:ignore
        subgroup_id=fields.get('subgroup_id'),
        account_id=fields.get('account_id'),
        contact_id=fields.get('contact_id'),
    )
    for field in ('reference', 'notes'):
        if field in fields:
            fields[field] = fields[field].strip()
    for field, value in fields.items():
        setattr(tx, field, value)
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            tx.save(update_fields=[*fields, 'updated_at'])
    except IntegrityError:
        raise ValidationError('Invalid transaction')
    return tx


def delete_transaction_service(*, user: User, transaction_id: int) -> None:
    tx = get_transaction_service(user=user, transaction_id=transaction_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        tx.delete()
