import datetime as dt
from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ProtectedError, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.companies.services import list_companies_service
from apps.finance.models import Contact, SubGroup, Transaction, TransactionStatus, TransactionType
from apps.finance.services import create_contact_service, create_series_service, create_transaction_service
from apps.sales.models import PERCENT_KINDS, Commission, Product, Sale, Salesperson, SaleStatus
from apps.users.models import User

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=16, decimal_places=2)


def _clean(name: str) -> str:
    return ' '.join(name.split())


# Products / salespeople: small configurable lists with the same shape

def _create_named(model, *, name: str, **extra):
    try:
        with transaction.atomic():
            return model.objects.create(name=_clean(name), **extra)
    except IntegrityError:
        raise ValidationError(f'{model._meta.verbose_name.capitalize()} with this name already exists')


def _update_named(obj, **fields):
    if 'name' in fields:
        fields['name'] = _clean(fields['name'])
    for field, value in fields.items():
        setattr(obj, field, value)
    try:
        with transaction.atomic():
            obj.save(update_fields=list(fields) or None)
    except IntegrityError:
        raise ValidationError(f'{obj._meta.verbose_name.capitalize()} with this name already exists')
    return obj


def _delete_protected(obj):
    try:
        obj.delete()
    except ProtectedError:
        raise ValidationError(f'{obj._meta.verbose_name.capitalize()} is in use by sales; deactivate it instead')


def create_product_service(*, name: str) -> Product:
    return _create_named(Product, name=name)


def list_products_service(*, active: bool | None = None):
    qs = Product.objects.all()
    return qs if active is None else qs.filter(active=active)


def update_product_service(*, product_id: int, **fields) -> Product:
    return _update_named(Product.objects.get(pk=product_id), **fields)


def delete_product_service(*, product_id: int) -> None:
    _delete_protected(Product.objects.get(pk=product_id))


def create_salesperson_service(*, name: str, user_id: int | None = None) -> Salesperson:
    return _create_named(Salesperson, name=name, user_id=user_id)


def list_salespeople_service(*, active: bool | None = None):
    qs = Salesperson.objects.all()
    return qs if active is None else qs.filter(active=active)


def update_salesperson_service(*, salesperson_id: int, **fields) -> Salesperson:
    return _update_named(Salesperson.objects.get(pk=salesperson_id), **fields)


def delete_salesperson_service(*, salesperson_id: int) -> None:
    _delete_protected(Salesperson.objects.get(pk=salesperson_id))


# Sales
# Access follows the company. Each sale carries how much was received so far.

def _received(status=TransactionStatus.REALIZED):
    return Coalesce(
        Sum('receivables__amount', filter=Q(
            receivables__status=status, receivables__type=TransactionType.INFLOW,
        )),
        Value(ZERO), output_field=MONEY,
    )


def _sales_for(user: User):
    return Sale.objects.filter(company__in=list_companies_service(user=user))


def _with_totals(qs):
    return qs.annotate(
        received_amount=_received(TransactionStatus.REALIZED),
        scheduled_amount=_received(TransactionStatus.PLANNED),
    ).select_related('company', 'contact', 'product', 'salesperson', 'delivery_responsible')


def _check_sale_refs(*, contact_id=None, product_id=None, salesperson_id=None, delivery_responsible_id=None):
    for model, pk, label in (
        (Contact, contact_id, 'Contact'), (Product, product_id, 'Product'),
        (Salesperson, salesperson_id, 'Salesperson'), (Salesperson, delivery_responsible_id, 'Delivery responsible'),
    ):
        if pk is not None and not model.objects.filter(pk=pk).exists():
            raise ValidationError(f'{label} does not exist')


def create_sale_service(*, user: User, company_id: int, date: dt.date, amount: Decimal, **fields) -> Sale:
    company = list_companies_service(user=user).get(pk=company_id)
    _check_sale_refs(**{k: fields.get(k) for k in (
        'contact_id', 'product_id', 'salesperson_id', 'delivery_responsible_id')})
    for field in ('payment_method', 'payment_terms', 'notes'):
        if field in fields:
            fields[field] = fields[field].strip()
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            sale = Sale.objects.create(company=company, date=date, amount=amount, **fields)
    except IntegrityError:
        raise ValidationError('Invalid sale')
    return get_sale_service(user=user, sale_id=sale.pk)


SALE_ORDERING = ('date', '-date', 'amount', '-amount', 'created_at', '-created_at')


def filter_sales(
    *, user: User, company_id=None, date_from=None, date_to=None, status=None, product_id=None,
    salesperson_id=None, delivery_responsible_id=None, contact_id=None, search: str | None = None,
    ordering: str | None = None,
):
    filters = {
        'company_id': company_id, 'date__gte': date_from, 'date__lte': date_to, 'status': status,
        'product_id': product_id, 'salesperson_id': salesperson_id,
        'delivery_responsible_id': delivery_responsible_id, 'contact_id': contact_id,
    }
    lookups = {}
    for key, value in filters.items():
        if value is None or value == []:
            continue
        lookups[f'{key}__in' if isinstance(value, (list, tuple, set)) else key] = value
    qs = _sales_for(user).filter(**lookups)
    if search:
        qs = qs.filter(
            Q(contact__name__icontains=search) | Q(contact__company_name__icontains=search)
            | Q(notes__icontains=search) | Q(payment_terms__icontains=search)
        )
    if ordering:
        if ordering not in SALE_ORDERING:
            raise ValidationError(f'Invalid ordering: {ordering}')
        qs = qs.order_by(ordering, '-id')
    return qs


def list_sales_service(*, user: User, **filters):
    # Totals join the receivables: aggregate over filter_sales(), never over this queryset
    return _with_totals(filter_sales(user=user, **filters))


def get_sale_service(*, user: User, sale_id: int) -> Sale:
    return _with_totals(_sales_for(user)).get(pk=sale_id)


def update_sale_service(*, user: User, sale_id: int, **fields) -> Sale:
    # ponytail: company is immutable, like transactions (receivables belong to it)
    sale = _sales_for(user).get(pk=sale_id)
    _check_sale_refs(**{k: fields.get(k) for k in (
        'contact_id', 'product_id', 'salesperson_id', 'delivery_responsible_id')})
    for field in ('payment_method', 'payment_terms', 'notes'):
        if field in fields:
            fields[field] = fields[field].strip()
    for field, value in fields.items():
        setattr(sale, field, value)
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            sale.save(update_fields=[*fields, 'updated_at'])
    except IntegrityError:
        raise ValidationError('Invalid sale')
    return get_sale_service(user=user, sale_id=sale.pk)


def delete_sale_service(*, user: User, sale_id: int) -> None:
    sale = _sales_for(user).get(pk=sale_id)
    try:
        with transaction.atomic(), pghistory.context(user=user.pk):
            sale.delete()
    except ProtectedError:
        raise ValidationError('Sale has receivables; delete or cancel them first')


def generate_receivables_service(
    *, user: User, sale_id: int, subgroup_id: int, first_date: dt.date, installments: int,
    down_payment: Decimal = ZERO, down_payment_date: dt.date | None = None,
    account_id: int | None = None,
) -> list[Transaction]:
    """Create the sale's receivables: optional down payment + installments for the rest.

    Covers what is still not scheduled (sale amount - receivables already linked).
    """
    sale = get_sale_service(user=user, sale_id=sale_id)
    if not SubGroup.objects.filter(pk=subgroup_id).exists():
        raise ValidationError('Subgroup does not exist')
    linked = sale.receivables.filter(type=TransactionType.INFLOW).aggregate(
        total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))['total']
    remaining = sale.amount - linked
    if remaining <= 0:
        raise ValidationError('Sale is already fully scheduled')
    if down_payment < 0 or down_payment >= remaining:
        raise ValidationError('Down payment must be lower than the amount to schedule')
    if installments < 1:
        raise ValidationError('installments must be at least 1')

    common = {
        'company_id': sale.company_id, 'subgroup_id': subgroup_id, 'type': TransactionType.INFLOW,  # type:ignore
        'account_id': account_id, 'contact_id': sale.contact_id, 'status': TransactionStatus.PLANNED,  # type:ignore
    }
    rest = remaining - down_payment
    with transaction.atomic(), pghistory.context(user=user.pk):
        created = []
        if down_payment > 0:
            created.append(create_transaction_service(
                user=user, date=down_payment_date or sale.date, amount=down_payment,
                reference='Entrada', **common,
            ))
        if installments == 1:
            created.append(create_transaction_service(user=user, date=first_date, amount=rest, **common))
        else:
            series = create_series_service(
                user=user, kind='installment', count=installments, first_date=first_date,
                total_amount=rest, **common,
            )
            created.extend(series.transactions.order_by('series_index'))
        Transaction.objects.filter(pk__in=[t.pk for t in created]).update(sale=sale)
    return list(Transaction.objects.filter(pk__in=[t.pk for t in created]).order_by('date', 'id'))


# Commissions
# Due the month after the sale, on the full sale amount (customer paid or not). Sellers and advisors
# get a % of the sale after the company's tax; the other kinds a fixed value.

CENT = Decimal('0.01')


def commission_amount(c: Commission) -> Decimal:
    if c.payment_id is not None and c.paid_amount is not None:  # type:ignore
        return c.paid_amount  # frozen when paid
    if c.kind in PERCENT_KINDS:
        after_tax = c.sale.amount * (1 - c.sale.company.tax_rate / 100)
        return (after_tax * c.percent / 100).quantize(CENT)  # type:ignore
    return c.fixed_amount or ZERO


def _commissions_for(user: User):
    return Commission.objects.filter(sale__company__in=list_companies_service(user=user)).select_related(
        'sale__company', 'sale__contact', 'salesperson', 'payment'
    )


def _commission_values(kind: str, percent, fixed_amount):
    if kind in PERCENT_KINDS:
        if percent is None:
            raise ValidationError('This kind of commission needs a percent')
        return percent, None
    if fixed_amount is None:
        raise ValidationError('This kind of commission needs a fixed amount')
    return None, fixed_amount


def list_sale_commissions_service(*, user: User, sale_id: int):
    _sales_for(user).get(pk=sale_id)
    return _commissions_for(user).filter(sale_id=sale_id).order_by('kind', 'id')


def create_commission_service(
    *, user: User, sale_id: int, salesperson_id: int, kind: str, percent=None, fixed_amount=None, description: str = '',
) -> Commission:
    sale = _sales_for(user).get(pk=sale_id)
    _check_sale_refs(salesperson_id=salesperson_id)
    percent, fixed_amount = _commission_values(kind, percent, fixed_amount)
    with transaction.atomic(), pghistory.context(user=user.pk):
        c = Commission.objects.create(
            sale=sale, salesperson_id=salesperson_id, kind=kind, percent=percent,
            fixed_amount=fixed_amount, description=description.strip(),
        )
    return _commissions_for(user).get(pk=c.pk)


def _editable_commission(user: User, commission_id: int) -> Commission:
    c = _commissions_for(user).get(pk=commission_id)
    if c.payment_id is not None:  # type:ignore
        raise ValidationError('Commission already paid: delete its payment first')
    return c


def update_commission_service(*, user: User, commission_id: int, **fields) -> Commission:
    c = _editable_commission(user, commission_id)
    if 'salesperson_id' in fields:
        _check_sale_refs(salesperson_id=fields['salesperson_id'])
    if 'description' in fields:
        fields['description'] = fields['description'].strip()
    for field, value in fields.items():
        setattr(c, field, value)
    c.percent, c.fixed_amount = _commission_values(c.kind, c.percent, c.fixed_amount)
    with transaction.atomic(), pghistory.context(user=user.pk):
        c.save()
    return _commissions_for(user).get(pk=c.pk)


def delete_commission_service(*, user: User, commission_id: int) -> None:
    c = _editable_commission(user, commission_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        c.delete()


def sales_month_for(due_month: dt.date) -> tuple[dt.date, dt.date]:
    """Commissions due in November come from the sales of October."""
    last = due_month.replace(day=1) - dt.timedelta(days=1)
    return last.replace(day=1), last


def list_commissions_service(*, user: User, month: dt.date | None = None, salesperson_id=None, company_id=None, status=None):
    # Canceled sale: its unpaid commissions disappear; paid ones stay on record
    qs = _commissions_for(user).exclude(sale__status=SaleStatus.CANCELED, payment__isnull=True)
    if month:
        qs = qs.filter(sale__date__range=sales_month_for(month))
    if salesperson_id:
        qs = qs.filter(salesperson_id__in=salesperson_id)
    if company_id:
        qs = qs.filter(sale__company_id__in=company_id)
    if status:
        qs = qs.filter(payment__isnull=status == 'pending')
    return qs.order_by('salesperson__name', 'sale__date', 'id')


def _contact_for(salesperson: Salesperson) -> Contact:
    return Contact.objects.filter(name__iexact=salesperson.name).order_by('pk').first() \
        or create_contact_service(name=salesperson.name)


def pay_commissions_service(*, user: User, ids: list[int], date: dt.date, subgroup_id: int) -> list[Transaction]:
    """One realized outflow per professional and company; the commissions get linked to it (paid)."""
    with transaction.atomic(), pghistory.context(user=user.pk):
        items = list(_commissions_for(user).filter(pk__in=ids).select_for_update(of=('self',)))
        if len(items) != len(set(ids)):
            raise Commission.DoesNotExist('One or more commissions do not exist')
        if any(c.payment_id is not None for c in items):  # type:ignore
            raise ValidationError('Some commissions are already paid')
        if any(c.sale.status == SaleStatus.CANCELED for c in items):
            raise ValidationError('Commissions of canceled sales cannot be paid')
        groups: dict[tuple[int, int], list[Commission]] = {}
        for c in items:
            groups.setdefault((c.salesperson_id, c.sale.company_id), []).append(c)  # type:ignore
        payments = []
        for group in groups.values():
            amounts = [commission_amount(c) for c in group]
            total = sum(amounts, ZERO)
            if total <= 0:
                raise ValidationError(f'Nothing to pay to {group[0].salesperson.name}')
            months = sorted({c.sale.date.strftime('%m/%Y') for c in group})
            tx = create_transaction_service(
                user=user, company_id=group[0].sale.company_id, subgroup_id=subgroup_id, date=date,  # type:ignore
                amount=total, type=TransactionType.OUTFLOW, status=TransactionStatus.REALIZED,
                contact_id=_contact_for(group[0].salesperson).pk,
                reference=f'Comissões vendas {", ".join(months)}'[:120],
                notes='\n'.join(f'{c.sale.contact.name if c.sale.contact else "Venda #" + str(c.sale_id)} · '  # type:ignore
                                 f'{c.get_kind_display()}: {a}' for c, a in zip(group, amounts)),
            )
            for c, a in zip(group, amounts):
                c.payment, c.paid_amount = tx, a
            Commission.objects.bulk_update(group, ['payment', 'paid_amount'])
            payments.append(tx)
    return payments
