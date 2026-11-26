from decimal import Decimal
from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import Field, HttpUrl
import datetime as dt

from apps.legal.models import AutoCheck, CaseComment, ChecklistItem, CollectionCase

Money = Field(ge=0, max_digits=14, decimal_places=2)
Required = Field(min_length=1)


class CreateCase(Schema):
    """Form "Ação de cobrança por inadimplência": every field is required."""
    company_id: int
    contact_id: int
    client_company: str = Required
    contact_info: str = Required
    delivered: str = Required
    proposal_amount: Decimal = Money
    paid_amount: Decimal = Money
    summary: str = Required
    drive_link: HttpUrl
    stage_id: int | None = None  # default: first stage
    agreement: str = ''


class PatchCase(Schema):
    client_company: str | None = Field(None, min_length=1)
    contact_info: str | None = Field(None, min_length=1)
    delivered: str | None = Field(None, min_length=1)
    proposal_amount: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    paid_amount: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    summary: str | None = Field(None, min_length=1)
    drive_link: HttpUrl | None = None
    process_number: str | None = Field(None, max_length=40)
    stage_id: int | None = None
    agreement: str | None = None
    unrecoverable: bool | None = None
    closed: bool | None = None
    responsible_id: int | None = None


class CaseOut(ModelSchema):
    company_id: int
    company_name: str = Field(alias='company.name')
    contact_id: int
    contact_name: str = Field(alias='contact.name')
    stage_id: int
    stage_name: str = Field(alias='stage.name')
    open_amount: Decimal  # agreement installments still planned
    received_amount: Decimal  # agreement installments realized
    defaulted_amount: Decimal  # defaulted installments suspended in the case (not its money)
    due_amount: Decimal  # still to come in: open agreement installments; before it, proposal - paid (else the defaulted ones)
    unrecoverable_by_name: str | None = None
    responsible_id: int | None
    responsible_name: str | None = None

    class Meta:
        model = CollectionCase
        fields = ['id', 'client_company', 'contact_info', 'delivered', 'proposal_amount', 'paid_amount',
                  'summary', 'drive_link', 'process_number', 'agreement', 'closed_at', 'unrecoverable_at', 'created_at', 'updated_at']

    @staticmethod
    def resolve_due_amount(obj) -> Decimal:
        if obj.closed_at or obj.stage.requires_agreement or obj.agreement.strip():
            return obj.open_amount
        if obj.proposal_amount is not None and obj.paid_amount is not None:  # balance the customer still owes
            return max(obj.proposal_amount - obj.paid_amount, Decimal('0'))
        return obj.defaulted_amount

    @staticmethod
    def resolve_responsible_name(obj) -> str | None:
        u = obj.responsible
        return (u.name or u.email) if u else None

    @staticmethod
    def resolve_unrecoverable_by_name(obj) -> str | None:
        u = obj.unrecoverable_by
        return (u.name or u.email) if u else None


class CaseFilters(Schema):
    stage: list[int] | None = None
    company_id: list[int] | None = None
    contact_id: int | None = None
    search: str | None = None


class CreateComment(Schema):
    text: str = Required


class CommentOut(ModelSchema):
    author_name: str | None = None

    class Meta:
        model = CaseComment
        fields = ['id', 'text', 'is_log', 'created_at']

    @staticmethod
    def resolve_author_name(obj: CaseComment) -> str | None:
        return (obj.author.name or obj.author.email) if obj.author else None  # type:ignore


class LegalStageIn(Schema):
    name: str = Field(min_length=1, max_length=60)
    position: int = Field(0, ge=0)
    requires_agreement: bool = False
    requires_checklist: bool = False
    requires_process_number: bool = False


class LegalStageOut(LegalStageIn):
    id: int



class PrefillOut(Schema):
    client_company: str
    contact_info: str
    delivered: str
    proposal_amount: Decimal | None
    paid_amount: Decimal
    summary: str


class CheckOut(Schema):
    item_id: int
    label: str
    required: bool
    auto: AutoCheck | None
    done: bool
    note: str
    checked_by_name: str | None
    checked_at: dt.datetime | None


class SetCheck(Schema):
    done: bool
    note: str = Field('', max_length=300)


class ChecklistItemIn(Schema):
    label: str = Field(min_length=1, max_length=160)
    required: bool = True
    active: bool = True
    position: int = Field(0, ge=0)
    auto: AutoCheck | Literal[''] = ''


class ChecklistItemOut(ModelSchema):
    class Meta:
        model = ChecklistItem
        fields = ['id', 'label', 'required', 'active', 'position', 'auto']


class ResponsibleOut(Schema):
    id: int
    name: str


class AgreementIn(Schema):
    """Registers the agreement: its installments (a previous agreement's open ones are replaced)."""
    stage_id: int | None = None  # default: first stage that requires the agreement
    text: str = ''
    down_payment: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    down_payment_date: dt.date | None = None
    total: Decimal = Field(gt=0, max_digits=14, decimal_places=2)  # whole agreement, down payment included
    count: int = Field(ge=1, le=120)
    first_due: dt.date


class BrokenAgreementIn(Schema):
    stage_id: int  # where the case goes back to

