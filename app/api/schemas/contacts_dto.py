from decimal import Decimal
from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import EmailStr

from apps.finance.models import Contact, ContactKind


class CreateContact(Schema):
    name: str
    kind: ContactKind = ContactKind.SUPPLIER
    company_name: str = ''
    document: str = ''
    email: EmailStr | Literal[''] = ''
    phone: str = ''
    notes: str = ''
    postal_code: str = ''
    address_number: str = ''
    address_complement: str = ''
    address_district: str = ''


class PatchContact(Schema):
    name: str | None = None
    kind: ContactKind | None = None
    company_name: str | None = None
    document: str | None = None
    email: EmailStr | Literal[''] | None = None
    phone: str | None = None
    notes: str | None = None
    postal_code: str | None = None
    address_number: str | None = None
    address_complement: str | None = None
    address_district: str | None = None


class MergeContacts(Schema):
    source_ids: list[int]  # duplicates folded into the contact of the URL, then deleted


Situation = Literal['ok', 'attention', 'critical']


class ContactOut(ModelSchema):
    situation: Situation | None = None  # customers only, on the list (PDF 15 traffic light)

    class Meta:
        model = Contact
        fields = ['id', 'name', 'kind', 'company_name', 'document', 'email', 'phone', 'notes',
                  'postal_code', 'address_number', 'address_complement', 'address_district', 'created_at', 'updated_at']


class ContactSalesSummary(Schema):
    sold: Decimal  # active + completed sales (canceled ones don't count)
    sales_count: int


class ContactMoneySummary(Schema):
    # As a customer (inflows)
    received: Decimal
    to_receive: Decimal  # planned, not due yet
    overdue_receivable: Decimal  # planned, due date already passed
    overdue_receivable_count: int
    # As a supplier (outflows)
    paid: Decimal
    to_pay: Decimal
    overdue_payable: Decimal
    overdue_payable_count: int
    pending_invoices: int


class ContactSummaryOut(Schema):
    """Each block is null when the user's role can't see that module."""
    sales: ContactSalesSummary | None
    money: ContactMoneySummary | None
    situation: Situation | None = None
