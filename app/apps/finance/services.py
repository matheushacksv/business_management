import calendar
import datetime as dt
from decimal import ROUND_DOWN, Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, CharField, Exists, OuterRef, ProtectedError, Q, Value, When

from apps.companies.services import list_companies_service, normalize_cnpj
from apps.attachments.models import Attachment
from apps.finance.models import (
    Account, Contact, Group, Invoice, InvoiceKind, SeriesKind, SubGroup, Transaction,
    TransactionSeries, TransactionStatus, TransactionType,
)
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
    return _transactions_for(user).select_related('company', 'subgroup', 'account', 'contact').get(pk=transaction_id)


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


# Invoices (NF) services
# Access follows the transaction's company.

def _invoices_for(user: User):
    return Invoice.objects.filter(
        transaction__company__in=list_companies_service(user=user)
    ).select_related('transaction')


def _validate_invoice(invoice: Invoice) -> None:
    if not invoice.done:
        return
    if not invoice.issue_date:
        raise ValidationError('A received/issued invoice needs its issue date')
    if invoice.direction == 'issue' and not invoice.number:
        raise ValidationError('An issued invoice needs its number')


def _save_invoice(user: User, invoice: Invoice, update_fields=None) -> Invoice:
    _validate_invoice(invoice)
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            invoice.save(update_fields=update_fields)
    except IntegrityError:
        raise ValidationError('This transaction already has an invoice of this kind')
    return invoice


def create_invoice_service(
    *, user: User, transaction_id: int, kind: str = InvoiceKind.SERVICE, done: bool = False,
    number: str = '', issue_date=None, notes: str = '',
) -> Invoice:
    tx = get_transaction_service(user=user, transaction_id=transaction_id)
    invoice = Invoice(
        transaction=tx, kind=kind, done=done, number=number.strip(),
        issue_date=issue_date, notes=notes.strip(),
    )
    return _save_invoice(user, invoice)


def list_invoices_service(*, user: User, transaction_id: int):
    tx = get_transaction_service(user=user, transaction_id=transaction_id)
    return _invoices_for(user).filter(transaction=tx)


def get_invoice_service(*, user: User, invoice_id: int) -> Invoice:
    return _invoices_for(user).get(pk=invoice_id)


def update_invoice_service(*, user: User, invoice_id: int, **fields) -> Invoice:
    invoice = get_invoice_service(user=user, invoice_id=invoice_id)
    for field in ('number', 'notes'):
        if field in fields:
            fields[field] = fields[field].strip()
    for field, value in fields.items():
        setattr(invoice, field, value)
    return _save_invoice(user, invoice, update_fields=[*fields, 'updated_at'])


def delete_invoice_service(*, user: User, invoice_id: int) -> None:
    invoice = get_invoice_service(user=user, invoice_id=invoice_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        invoice.delete()


INVOICE_PENDING_REASONS = ('missing_invoice', 'missing_attachment')


def pending_invoices_service(
    *, user: User, company_id=None, date_from=None, date_to=None,
    direction: str | None = None, kind: str | None = None, reason: str | None = None,
):
    """NFs still pending: not received/issued yet, or done but without the file attached."""
    has_attachment = Attachment.objects.filter(
        content_type=ContentType.objects.get_for_model(Invoice), object_id=OuterRef('pk')
    )
    qs = (
        _invoices_for(user)
        .annotate(
            has_attachment=Exists(has_attachment),
            pending_reason=Case(
                When(done=False, then=Value('missing_invoice')),
                default=Value('missing_attachment'),
                output_field=CharField(),
            ),
        )
        .filter(Q(done=False) | Q(has_attachment=False))
        .select_related('transaction__company', 'transaction__contact')
    )
    filters = {
        'transaction__company_id__in': company_id, 'transaction__date__gte': date_from,
        'transaction__date__lte': date_to, 'kind': kind, 'pending_reason': reason,
        'transaction__type': {'receive': TransactionType.OUTFLOW, 'issue': TransactionType.INFLOW}.get(direction or ''),
    }
    return qs.filter(**{k: v for k, v in filters.items() if v not in (None, [])})


# Series services (installments / recurring)

MAX_SERIES_COUNT = 120  # 10 years of monthly occurrences
SERIES_EDITABLE_FIELDS = ('amount', 'subgroup_id', 'account_id', 'contact_id', 'reference', 'notes')


def add_months(day: dt.date, months: int) -> dt.date:
    """Same day N months later, clamped to the month's last day (Jan 31 -> Feb 28)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def split_amount(total: Decimal, count: int) -> list[Decimal]:
    """Even split in cents; the remainder goes to the first installment so the sum is exact."""
    base = (total / count).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    return [total - base * (count - 1)] + [base] * (count - 1)


def create_series_service(
    *, user: User, kind: str, count: int, first_date: dt.date, company_id: int, subgroup_id: int,
    type: str, amount: Decimal | None = None, total_amount: Decimal | None = None,
    status: str = TransactionStatus.PLANNED, account_id: int | None = None,
    contact_id: int | None = None, reference: str = '', notes: str = '',
) -> TransactionSeries:
    # ponytail: fixed-length only; open-ended recurrence needs a scheduler creating future rows
    if not 1 <= count <= MAX_SERIES_COUNT:
        raise ValidationError(f'count must be between 1 and {MAX_SERIES_COUNT}')
    if kind == SeriesKind.INSTALLMENT:
        if count < 2:
            raise ValidationError('An installment plan needs at least 2 installments')
        if total_amount is None or amount is not None:
            raise ValidationError('Installments take total_amount (not amount)')
        if total_amount < Decimal('0.01') * count:
            raise ValidationError('total_amount is too small for this many installments')
        amounts = split_amount(total_amount, count)
    else:
        if amount is None or total_amount is not None:
            raise ValidationError('Recurring transactions take amount (not total_amount)')
        amounts = [amount] * count
    if any(a <= 0 for a in amounts):
        raise ValidationError('Amounts must be positive')

    company = list_companies_service(user=user).get(pk=company_id)
    _check_refs(company_id=company.pk, subgroup_id=subgroup_id, account_id=account_id, contact_id=contact_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        series = TransactionSeries.objects.create(
            company=company, kind=kind, count=count, total_amount=sum(amounts), created_by=user,
        )
        Transaction.objects.bulk_create(
            Transaction(
                company=company, subgroup_id=subgroup_id, account_id=account_id, contact_id=contact_id,
                date=add_months(first_date, i), amount=value, type=type, status=status,
                reference=reference.strip(), notes=notes.strip(), series=series, series_index=i + 1,
            )
            for i, value in enumerate(amounts)
        )
    return series


def get_series_service(*, user: User, series_id: int) -> TransactionSeries:
    return TransactionSeries.objects.filter(
        company__in=list_companies_service(user=user)
    ).get(pk=series_id)


def series_transactions_service(*, user: User, series_id: int):
    series = get_series_service(user=user, series_id=series_id)
    return series.transactions.select_related('company', 'subgroup', 'account', 'contact').order_by('series_index') #type:ignore


def update_series_service(*, user: User, series_id: int, from_index: int = 1, **fields) -> int:
    """Apply the same change to occurrence `from_index` and every later one. Returns rows changed."""
    series = get_series_service(user=user, series_id=series_id)
    unknown = set(fields) - set(SERIES_EDITABLE_FIELDS)
    if unknown:
        raise ValidationError(f'Fields not editable on a series: {sorted(unknown)}')
    if not fields:
        return 0
    if 'amount' in fields and fields['amount'] <= 0:
        raise ValidationError('Amounts must be positive')
    _check_refs(
        company_id=series.company_id,  # type:ignore
        subgroup_id=fields.get('subgroup_id'), account_id=fields.get('account_id'),
        contact_id=fields.get('contact_id'),
    )
    for field in ('reference', 'notes'):
        if field in fields:
            fields[field] = fields[field].strip()
    with transaction.atomic(), pghistory.context(user=user.pk):
        return series.transactions.filter(series_index__gte=from_index).update( #type:ignore
            **fields, updated_at=timezone.now()
        )


def cancel_series_service(*, user: User, series_id: int, from_index: int = 1) -> int:
    """Delete PLANNED occurrences from `from_index` on. Realized ones are history and stay."""
    series = get_series_service(user=user, series_id=series_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        deleted, _ = series.transactions.filter(    #type:ignore
            series_index__gte=from_index, status=TransactionStatus.PLANNED
        ).delete()
        if not series.transactions.exists():    #type:ignore
            series.delete()
    return deleted

