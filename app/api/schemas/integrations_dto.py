import datetime as dt

from ninja import Schema

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


class CredentialsOut(Schema):
    username: str
    password: str


class EventOut(Schema):
    id: int
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
