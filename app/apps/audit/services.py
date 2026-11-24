"""Read side of the audit trail (pghistory): who changed what, when, and the previous values."""

from dataclasses import dataclass
from typing import Callable

import pghistory.models
from django.apps import apps as django_apps
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import models

from apps.attachments.services import TARGETS as ATTACHMENT_TARGETS
from apps.companies.services import get_company_service, list_companies_service
from apps.finance.models import Account, SubGroup
from apps.finance.services import get_account_service, get_subgroup_service
from apps.investments.models import Investment, Movement
from apps.investments.services import get_investment_service
from apps.sales.models import Commission, Product, Salesperson
from apps.users.models import User
from apps.users.permissions import VIEW, check_permission
from apps.users.services import get_user_service


@dataclass(frozen=True)
class Target:
    model: type[models.Model]
    module: str
    get: Callable[[User, int], models.Model]  # scoped getter (company access)


TARGETS: dict[str, Target] = {
    **{name: Target(t.model, t.module, t.get) for name, t in ATTACHMENT_TARGETS.items()},
    'company': Target(django_apps.get_model('companies', 'Company'), 'companies',
                      lambda user, pk: get_company_service(user=user, company_id=pk)),
    'subgroup': Target(SubGroup, 'subgroups', lambda user, pk: get_subgroup_service(subgroup_id=pk)),
    'account': Target(Account, 'accounts', lambda user, pk: get_account_service(user=user, account_id=pk)),
    'product': Target(Product, 'sales', lambda user, pk: Product.objects.get(pk=pk)),
    'salesperson': Target(Salesperson, 'sales', lambda user, pk: Salesperson.objects.get(pk=pk)),
    'user': Target(User, 'users', lambda user, pk: get_user_service(user_id=pk)),
    'investment': Target(Investment, 'investments', lambda user, pk: get_investment_service(user=user, investment_id=pk)),
    'movement': Target(Movement, 'investments', lambda user, pk: Movement.objects.get(
        pk=pk, investment__company__in=list_companies_service(user=user))),
    'commission': Target(Commission, 'sales', lambda user, pk: Commission.objects.get(
        pk=pk, sale__company__in=list_companies_service(user=user))),
}


def _event_model(model: type[models.Model]):
    # pghistory names the event model "<Model>Event" in the same app
    return django_apps.get_model(model._meta.app_label, f'{model.__name__}Event')


def _serialize(events) -> list[dict]:
    user_ids = {e.pgh_context.get('user') for e in events if e.pgh_context and e.pgh_context.get('user')}
    emails = dict(User.objects.filter(pk__in=user_ids).values_list('pk', 'email'))
    out = []
    for e in events:
        context = e.pgh_context or {}
        out.append({
            'id': e.pgh_slug,
            'action': e.pgh_label,                      # insert / update / delete
            'created_at': e.pgh_created_at,
            'target': e.pgh_obj_model.split('.')[-1].lower(),
            'target_id': int(e.pgh_obj_id) if e.pgh_obj_id else None,
            'user_id': context.get('user'),
            'user_email': emails.get(context.get('user')),
            'source': context.get('source'),            # e.g. spreadsheet_import
            'changes': e.pgh_diff or {},                # {field: [old, new]}
            'data': e.pgh_data,                         # full snapshot after the event
        })
    return out


def object_history_service(*, user: User, target: str, target_id: int) -> list[dict]:
    if target not in TARGETS:
        raise ValidationError(f'Invalid target: {target}')
    spec = TARGETS[target]
    check_permission(user, spec.module, VIEW)
    events = pghistory.models.Events.objects.across(_event_model(spec.model)).filter(pgh_obj_id=str(target_id))
    try:
        spec.get(user, target_id)
    except ObjectDoesNotExist:
        # Deleted records keep their history ("who deleted it?"), visible to admins only
        if not (user.is_admin and events.exists()):
            raise
    return _serialize(list(events.order_by('pgh_created_at', 'pgh_id')))


def tracked_event_models() -> list:
    from apps.attachments.models import Attachment  # uploads/deletions show up in the feed too

    return [_event_model(t.model) for t in TARGETS.values()] + [_event_model(Attachment)]


def activity_feed_service(
    *, user: User, user_id: int | None = None, target: str | None = None,
    date_from=None, date_to=None,
):
    """Every change across the system, newest first. Admin only (PDF: audit each user's work)."""
    if not user.is_admin:
        raise PermissionDenied('Only administrators can see the activity feed')
    if target and target not in TARGETS:
        raise ValidationError(f'Invalid target: {target}')
    # ponytail: UNION over every event table + diff subqueries; add per-table indexes if it gets slow
    models_ = [_event_model(TARGETS[target].model)] if target else tracked_event_models()
    qs = pghistory.models.Events.objects.across(*models_)
    if user_id is not None:
        qs = qs.filter(pgh_context__user=user_id)
    if date_from:
        qs = qs.filter(pgh_created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(pgh_created_at__date__lte=date_to)
    return qs.order_by('-pgh_created_at', '-pgh_id')


def serialize_events(events) -> list[dict]:
    return _serialize(list(events))
