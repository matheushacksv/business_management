from decimal import Decimal

from ninja import ModelSchema, Schema
from pydantic import Field, HttpUrl

from apps.legal.models import CaseComment, CaseStage, CollectionCase

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
    stage: CaseStage = CaseStage.NEW
    agreement: str = ''


class PatchCase(Schema):
    client_company: str | None = Field(None, min_length=1)
    contact_info: str | None = Field(None, min_length=1)
    delivered: str | None = Field(None, min_length=1)
    proposal_amount: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    paid_amount: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    summary: str | None = Field(None, min_length=1)
    drive_link: HttpUrl | None = None
    stage: CaseStage | None = None
    agreement: str | None = None


class CaseOut(ModelSchema):
    company_id: int
    company_name: str = Field(alias='company.name')
    contact_id: int
    contact_name: str = Field(alias='contact.name')
    open_amount: Decimal  # linked installments still planned: what is owed
    received_amount: Decimal  # linked installments realized

    class Meta:
        model = CollectionCase
        fields = ['id', 'client_company', 'contact_info', 'delivered', 'proposal_amount', 'paid_amount',
                  'summary', 'drive_link', 'stage', 'agreement', 'created_at', 'updated_at']


class CaseFilters(Schema):
    stage: list[CaseStage] | None = None
    company_id: list[int] | None = None
    contact_id: int | None = None
    search: str | None = None


class CreateComment(Schema):
    text: str = Required


class CommentOut(ModelSchema):
    author_name: str | None = None

    class Meta:
        model = CaseComment
        fields = ['id', 'text', 'created_at']

    @staticmethod
    def resolve_author_name(obj: CaseComment) -> str | None:
        return (obj.author.name or obj.author.email) if obj.author else None  # type:ignore


class StageOut(Schema):
    value: str
    label: str

