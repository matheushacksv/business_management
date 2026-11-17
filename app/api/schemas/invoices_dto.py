import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import Field, model_validator

from apps.finance.models import Invoice, InvoiceKind


class CreateInvoice(Schema):
    transaction_id: int
    kind: InvoiceKind = InvoiceKind.SERVICE
    done: bool = False
    number: str = ''
    issue_date: dt.date | None = None
    notes: str = ''


class PatchInvoice(Schema):
    kind: InvoiceKind | None = None
    done: bool | None = None
    number: str | None = None
    issue_date: dt.date | None = None  # null clears it
    notes: str | None = None

    @model_validator(mode='after')
    def reject_null_on_required(self):
        for field in ('kind', 'done', 'number', 'notes'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null')
        return self


class InvoiceOut(ModelSchema):
    transaction_id: int
    direction: Literal['receive', 'issue']

    class Meta:
        model = Invoice
        fields = ['id', 'kind', 'done', 'number', 'issue_date', 'notes', 'created_at', 'updated_at']


class PendingInvoiceOut(InvoiceOut):
    pending_reason: Literal['missing_invoice', 'missing_attachment']
    transaction_date: dt.date = Field(alias='transaction.date')
    transaction_amount: Decimal = Field(alias='transaction.amount')
    company_id: int = Field(alias='transaction.company_id')
    company_name: str = Field(alias='transaction.company.name')
    contact_name: str | None = None

    @staticmethod
    def resolve_contact_name(obj: Invoice) -> str | None:
        contact = obj.transaction.contact
        return contact.name if contact else None


class PendingInvoiceFilters(Schema):
    company_id: list[int] | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    direction: Literal['receive', 'issue'] | None = None
    kind: InvoiceKind | None = None
    reason: Literal['missing_invoice', 'missing_attachment'] | None = None
    contact_id: int | None = None
