import datetime as dt
from typing import Any, Literal

from ninja import Query, Router, Schema
from pydantic import Field

from apps.audit import services

router = Router(tags=['History'])

TargetName = Literal[
    'transaction', 'contact', 'invoice', 'sale', 'company', 'subgroup', 'account',
    'product', 'salesperson', 'user',
]  # attachment events show up in the feed (unfiltered)
FEED_PAGE_SIZE = 50


class HistoryEventOut(Schema):
    id: str
    action: str
    created_at: dt.datetime
    target: str
    target_id: int | None
    user_id: int | None
    user_email: str | None
    source: str | None
    changes: dict[str, Any]  # {field: [old, new]}
    data: dict[str, Any]


class FeedFilters(Schema):
    user_id: int | None = None
    target: TargetName | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    page: int = Field(1, ge=1)


class FeedOut(Schema):
    count: int
    items: list[HistoryEventOut]


@router.get('/history', response=list[HistoryEventOut])
def object_history_endpoint(request, target: TargetName, target_id: int):
    """Every change of one record, oldest first. Permission = view on the record's module."""
    return services.object_history_service(user=request.user, target=target, target_id=target_id)


@router.get('/history/feed', response=FeedOut)
def activity_feed_endpoint(request, filters: Query[FeedFilters]):
    """All changes across the system, newest first (admins). Filter by user to audit their work."""
    data = filters.dict()
    page = data.pop('page')
    qs = services.activity_feed_service(user=request.user, **data)
    start = (page - 1) * FEED_PAGE_SIZE
    return {
        'count': qs.count(),
        'items': services.serialize_events(qs[start:start + FEED_PAGE_SIZE]),
    }
