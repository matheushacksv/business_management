"""Investments: CRUD, movements (with their cash leg) and the position of each investment.

Access follows the company (list_companies_service), like accounts and transactions."""

import datetime as dt
from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.companies.services import list_companies_service
from apps.finance.models import (
    INVESTMENT_SUBGROUP_NAME, Account, Group, SubGroup, Transaction, TransactionStatus, TransactionType,
)
from apps.investments.models import Holder, Investment, Movement, MovementKind
from apps.users.models import User

ZERO = Decimal('0')
TEXT_FIELDS = ('institution', 'description', 'notes')


def _investments_for(user: User):
    return Investment.objects.filter(company__in=list_companies_service(user=user)).select_related('company')


def _clean(fields: dict) -> dict:
    for key in TEXT_FIELDS:
        if key in fields and fields[key] is not None:
            fields[key] = fields[key].strip()
    if 'institution' in fields and not fields['institution']:
        raise ValidationError('Informe a instituição')
    return fields


def position(inv: Investment, as_of: dt.date | None = None) -> dict:
    """Balance = last informed balance + applications − redemptions after it.
    Yield = balance − (applied − redeemed)."""
    applied = redeemed = balance = ZERO
    balance_date = None
    for m in inv.movements.all():  # prefetched, ordered by date
        if as_of and m.date > as_of:
            break
        if m.kind == MovementKind.APPLICATION:
            applied += m.amount
            balance += m.amount
        elif m.kind == MovementKind.REDEMPTION:
            redeemed += m.amount
            balance -= m.amount
        else:
            balance, balance_date = m.amount, m.date
    gain = balance - (applied - redeemed)
    invested = applied - redeemed
    return {'applied': applied, 'redeemed': redeemed, 'balance': balance, 'yield_amount': gain,
            'yield_percent': (gain / invested * 100).quantize(Decimal('0.01')) if invested > 0 else None,
            'balance_date': balance_date}


def _with_position(inv: Investment, as_of=None) -> Investment:
    for key, value in position(inv, as_of).items():
        setattr(inv, key, value)
    return inv


def list_investments_service(*, user: User, holder=None, company_id=None, institution=None, active=None, as_of=None):
    qs = _investments_for(user).prefetch_related('movements')
    if holder:
        qs = qs.filter(holder=holder)
    if company_id:
        qs = qs.filter(company_id__in=company_id)
    if institution:
        qs = qs.filter(institution__icontains=institution.strip())
    if active is not None:
        qs = qs.filter(active=active)
    return [_with_position(inv, as_of) for inv in qs]


def get_investment_service(*, user: User, investment_id: int) -> Investment:
    return _with_position(_investments_for(user).prefetch_related('movements').get(pk=investment_id))


def create_investment_service(*, user: User, company_id: int, **fields) -> Investment:
    company = list_companies_service(user=user).get(pk=company_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        inv = Investment.objects.create(company=company, **_clean(fields))
    return get_investment_service(user=user, investment_id=inv.pk)


def update_investment_service(*, user: User, investment_id: int, **fields) -> Investment:
    inv = _investments_for(user).get(pk=investment_id)
    if 'company_id' in fields and fields['company_id'] != inv.company_id:  # type:ignore
        if inv.movements.exclude(transaction=None).exists():  # type:ignore
            raise ValidationError('Movimentos já lançados no caixa desta empresa: exclua-os antes de trocar a empresa')
        fields['company'] = list_companies_service(user=user).get(pk=fields.pop('company_id'))
    if fields.get('holder') == Holder.PERSONAL and inv.movements.exclude(transaction=None).exists():  # type:ignore
        raise ValidationError('Movimentos já lançados no caixa: exclua-os antes de tornar o investimento pessoal')
    for key, value in _clean(fields).items():
        setattr(inv, key, value)
    with transaction.atomic(), pghistory.context(user=user.pk):
        inv.save()
    return get_investment_service(user=user, investment_id=inv.pk)


def delete_investment_service(*, user: User, investment_id: int) -> None:
    inv = _investments_for(user).get(pk=investment_id)
    if inv.movements.exists():  # type:ignore
        raise ValidationError('Investimento com movimentos: exclua os movimentos ou desative-o')
    with transaction.atomic(), pghistory.context(user=user.pk):
        inv.delete()


# Movements

def _investment_subgroup() -> SubGroup:
    return SubGroup.objects.get_or_create(group=Group.TRANSFER, name=INVESTMENT_SUBGROUP_NAME)[0]


def create_movement_service(
    *, user: User, investment_id: int, date: dt.date, kind: str, amount: Decimal,
    account_id: int | None = None, notes: str = '',
) -> Movement:
    inv = _investments_for(user).get(pk=investment_id)
    if kind != MovementKind.BALANCE and amount <= 0:
        raise ValidationError('Valor deve ser maior que zero')
    cash = kind != MovementKind.BALANCE and inv.holder == Holder.COMPANY and account_id is not None
    if account_id is not None and not cash:
        raise ValidationError('Conta só se aplica a aplicação/resgate de investimento da empresa')
    if cash and not Account.objects.filter(pk=account_id, company_id=inv.company_id).exists():  # type:ignore
        raise ValidationError('Conta não pertence à empresa do investimento')
    if kind == MovementKind.REDEMPTION and amount > position(inv, date)['balance']:
        raise ValidationError('Resgate maior que o saldo do investimento nessa data')
    with transaction.atomic(), pghistory.context(user=user.pk):
        tx = None
        if cash:
            application = kind == MovementKind.APPLICATION
            tx = Transaction.objects.create(
                company_id=inv.company_id, account_id=account_id, subgroup=_investment_subgroup(),  # type:ignore
                date=date, amount=amount, status=TransactionStatus.REALIZED,
                type=TransactionType.OUTFLOW if application else TransactionType.INFLOW,
                reference=f'{"Aplicação" if application else "Resgate"} {inv.institution}'[:120],
                notes=(inv.description or notes.strip()),
            )
        return Movement.objects.create(investment=inv, date=date, kind=kind, amount=amount, notes=notes.strip(),
                                       transaction=tx)


def delete_movement_service(*, user: User, movement_id: int) -> None:
    m = Movement.objects.select_related('transaction').get(
        pk=movement_id, investment__company__in=list_companies_service(user=user))
    with transaction.atomic(), pghistory.context(user=user.pk):
        tx = m.transaction
        m.delete()
        if tx:
            tx.delete()

