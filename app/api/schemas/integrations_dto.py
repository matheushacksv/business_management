import datetime as dt
from decimal import Decimal

from ninja import Schema
from pydantic import Field

from apps.integrations.models import EventStatus


class PipedriveConfigOut(Schema):
    username: str
    user_email: str | None = None
    subgroup_id: int | None

    @staticmethod
    def resolve_user_email(obj) -> str | None:
        return obj.user.email if obj.user else None


class PipedriveConfigIn(Schema):
    subgroup_id: int | None


class AsaasConfigOut(Schema):
    company_id: int
    company_name: str
    has_key: bool
    sandbox: bool
    webhook_token: str
    account_id: int | None
    fine_percent: Decimal
    interest_percent: Decimal
    invoice_percent: Decimal
    service_id: str
    service_name: str
    iss_rate: Decimal
    description_template: str


class AsaasConfigIn(Schema):
    api_key: str | None = None  # write-only; empty keeps the current one
    sandbox: bool
    account_id: int | None
    fine_percent: Decimal = Field(ge=0, le=100)
    interest_percent: Decimal = Field(ge=0, le=100)
    invoice_percent: Decimal = Field(gt=0, le=100)
    service_id: str
    service_name: str
    iss_rate: Decimal = Field(ge=0, le=100)
    description_template: str


class ChargesOut(Schema):
    created: int


class CredentialsOut(Schema):
    username: str
    password: str


class EventOut(Schema):
    id: int
    source: str
    key: str
    status: EventStatus
    message: str
    sale_id: int | None
    payload: dict
    received_at: dt.datetime
    processed_at: dt.datetime | None


class WebhookResult(Schema):
    status: EventStatus
    message: str
    sale_id: int | None


class PhoneLineOut(Schema):
    user_id: int
    name: str
    email: str  # API4COM login
    extension: str
    valid: bool
    updated_at: dt.datetime


class PhoneLineIn(Schema):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class CallOut(Schema):
    id: int
    activity_id: int | None
    activity_title: str | None = None
    user_name: str | None = None
    called: str
    created_at: dt.datetime
    answered_at: dt.datetime | None
    ended_at: dt.datetime | None
    duration: int | None
    record_url: str

    @staticmethod
    def resolve_activity_title(obj) -> str | None:
        return obj.activity.title if obj.activity else None

    @staticmethod
    def resolve_user_name(obj) -> str | None:
        return (obj.user.name or obj.user.email) if obj.user else None
