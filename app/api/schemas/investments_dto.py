import datetime as dt
from decimal import Decimal

from ninja import ModelSchema, Schema
from pydantic import Field

from apps.investments.models import Holder, Investment, InvestmentKind, Movement, MovementKind


class InvestmentFilters(Schema):
    holder: Holder | None = None
    company_id: list[int] | None = None
    institution: str | None = None
    active: bool | None = None
    as_of: dt.date | None = None  # position on that date (default: today and beyond)


class CreateInvestment(Schema):
    company_id: int
    holder: Holder = Holder.COMPANY
    institution: str = Field(min_length=1, max_length=120)
    kind: InvestmentKind = InvestmentKind.CDB
    description: str = Field('', max_length=160)
    notes: str = ''
    active: bool = True


class PatchInvestment(Schema):
    company_id: int | None = None
    holder: Holder | None = None
    institution: str | None = Field(None, min_length=1, max_length=120)
    kind: InvestmentKind | None = None
    description: str | None = Field(None, max_length=160)
    notes: str | None = None
    active: bool | None = None


class InvestmentOut(ModelSchema):
    company_id: int
    company_name: str = Field(alias='company.name')
    applied: Decimal
    redeemed: Decimal
    balance: Decimal
    yield_amount: Decimal
    yield_percent: Decimal | None
    balance_date: dt.date | None

    class Meta:
        model = Investment
        fields = ['id', 'holder', 'institution', 'kind', 'description', 'notes', 'active', 'created_at']


class CreateMovement(Schema):
    date: dt.date
    kind: MovementKind
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    account_id: int | None = None  # company investment: the account the money leaves/arrives (cash leg)
    notes: str = Field('', max_length=200)


class MovementOut(ModelSchema):
    investment_id: int
    transaction_id: int | None
    account_name: str | None = Field(None, alias='transaction.account.name')

    class Meta:
        model = Movement
        fields = ['id', 'date', 'kind', 'amount', 'notes', 'created_at']
