import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import Field, model_validator

from apps.finance.models import Group, Transaction, TransactionStatus, TransactionType


class CreateTransaction(Schema):
    company_id: int
    subgroup_id: int
    date: dt.date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    type: TransactionType
    status: TransactionStatus = TransactionStatus.PLANNED
    account_id: int | None = None
    contact_id: int | None = None
    reference: str = ''
    notes: str = ''


class PatchTransaction(Schema):
    subgroup_id: int | None = None
    date: dt.date | None = None
    amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    type: TransactionType | None = None
    status: TransactionStatus | None = None
    account_id: int | None = None
    contact_id: int | None = None
    reference: str | None = None
    notes: str | None = None

    # account_id/contact_id accept null (unlink); the rest can't be nulled
    @model_validator(mode='after')
    def reject_null_on_required(self):
        for field in ('subgroup_id', 'date', 'amount', 'type', 'status', 'reference', 'notes'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null')
        return self


class ReportFilters(Schema):
    # Shared by the transaction list and the reports.
    # list[...] fields are multi-select: ?subgroup_id=1&subgroup_id=2
    company_id: list[int] | None = None
    status: list[TransactionStatus] | None = None
    type: list[TransactionType] | None = None
    group: list[Group] | None = None
    subgroup_id: list[int] | None = None
    account_id: list[int] | None = None
    contact_id: list[int] | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    search: str | None = None


class TransactionFilters(ReportFilters):
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    ordering: Literal['date', '-date', 'amount', '-amount', 'created_at', '-created_at'] | None = None


class TransactionOut(ModelSchema):
    group: Group = Field(alias='subgroup.group')
    is_reversal: bool

    class Meta:
        model = Transaction
        fields = [
            'id', 'company', 'subgroup', 'account', 'contact', 'date', 'amount',
            'type', 'status', 'reference', 'notes', 'created_at', 'updated_at',
        ]
