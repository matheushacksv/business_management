import datetime as dt
from decimal import Decimal

from typing import Literal

from ninja import Schema
from pydantic import Field

from apps.dunning.models import ActivityKind, Outcome, Severity


class StageIn(Schema):
    name: str = Field(min_length=1, max_length=60)
    position: int = Field(0, ge=0)
    severity: Severity = Severity.ATTENTION


class StageOut(StageIn):
    id: int


class StepIn(Schema):
    day: int = Field(ge=1, le=365)
    kind: ActivityKind
    title: str = Field(min_length=1, max_length=120)
    template: str = ''
    active: bool = True


class StepOut(StepIn):
    id: int


class CardFilters(Schema):
    outcome: Outcome = Outcome.OPEN
    assignee_id: int | None = None
    company_id: list[int] | None = None
    search: str | None = None


class CardOut(Schema):
    id: int
    company_id: int
    company_name: str = Field(alias='company.name')
    contact_id: int
    contact_name: str = Field(alias='contact.name')
    contact_phone: str = Field(alias='contact.phone')
    contact_email: str = Field(alias='contact.email')
    stage_id: int
    assignee_id: int | None
    assignee_name: str | None = None
    overdue_since: dt.date
    closed_at: dt.date | None
    outcome: Outcome
    legal_case_id: int | None
    overdue_amount: Decimal
    overdue_count: int
    oldest_overdue: dt.date | None = None  # days late count from here
    next_activity: dt.date | None
    late_activities: int
    critical: bool

    @staticmethod
    def resolve_assignee_name(obj) -> str | None:
        return (obj.assignee.name or obj.assignee.email) if obj.assignee else None


class PatchCard(Schema):
    stage_id: int | None = None
    assignee_id: int | None = None
    outcome: Literal[Outcome.RESOLVED, Outcome.LEGAL] | None = None
    legal_case_id: int | None = None  # outcome legal: the case opened with the legal form


class InstallmentOut(Schema):
    id: int
    date: dt.date
    amount: Decimal
    reference: str
    sale_id: int | None


class ActivityIn(Schema):
    kind: ActivityKind
    title: str = Field(min_length=1, max_length=120)
    message: str = ''
    due_date: dt.date


class PatchActivity(Schema):
    done: bool | None = None
    answered: bool | None = None
    notes: str | None = None
    due_date: dt.date | None = None
    title: str | None = Field(None, min_length=1, max_length=120)
    message: str | None = None


class ActivityOut(Schema):
    id: int
    card_id: int
    kind: ActivityKind
    title: str
    message: str
    due_date: dt.date
    done_at: dt.datetime | None
    done_by_name: str | None = None
    answered: bool | None
    notes: str

    @staticmethod
    def resolve_done_by_name(obj) -> str | None:
        return (obj.done_by.name or obj.done_by.email) if obj.done_by else None


class AgendaOut(ActivityOut):
    contact_name: str = Field(alias='card.contact.name')
    company_name: str = Field(alias='card.company.name')
    assignee_name: str | None = None

    @staticmethod
    def resolve_assignee_name(obj) -> str | None:
        a = obj.card.assignee
        return (a.name or a.email) if a else None


class AssigneeOut(Schema):
    id: int
    name: str | None
    email: str


class ProductivityParams(Schema):
    start: dt.date
    end: dt.date


class PersonProductivity(Schema):
    user_id: int | None
    name: str
    done: int
    messages: int
    calls: int
    no_answer: int
    pending: int
    late: int


class ProductivityOut(Schema):
    open_cards: int
    overdue_amount: Decimal
    resolved: int
    to_legal: int
    people: list[PersonProductivity]


class ConfigIO(Schema):
    start_date: dt.date | None
    critical_days: int = Field(30, ge=1, le=365)
    attention_days: int = Field(1, ge=1, le=365)
    legal_critical: bool = True


class NoteIn(Schema):
    text: str = Field(min_length=1)


class NoteOut(Schema):
    id: int
    text: str
    author_name: str | None = None
    created_at: dt.datetime

    @staticmethod
    def resolve_author_name(obj) -> str | None:
        return (obj.author.name or obj.author.email) if obj.author else None
