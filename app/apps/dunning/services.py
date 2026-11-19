import datetime as dt
from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, F, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.companies.services import list_companies_service
from apps.dunning.models import Activity, CadenceStep, Card, Config, Stage, StageKind
from apps.finance.models import Transaction, TransactionStatus, TransactionType
from apps.legal.services import create_case_service
from apps.users.models import User
from apps.users.permissions import CHANGE, CREATE, check_permission, has_permission

MONEY = DecimalField(max_digits=16, decimal_places=2)
ZERO = Decimal('0')


def _late(today: dt.date):
    """Installments the customer should have paid already and that are not with the legal team."""
    return Transaction.objects.filter(
        type=TransactionType.INFLOW, status=TransactionStatus.PLANNED, date__lt=today,
        collection_case__isnull=True, contact__isnull=False,
    )


def _overdue(today: dt.date):
    """What opens cards automatically: late installments due from the configured start date on."""
    start = Config.get().start_date
    return _late(today).filter(date__gte=start) if start else _late(today)


def _overdue_of(card: Card, today: dt.date):
    # from the card's own start: a card sent by hand may hold installments older than the start date
    return _late(today).filter(company_id=card.company_id, contact_id=card.contact_id, date__gte=card.overdue_since)  # type:ignore


def _open_card(company_id: int, contact_id: int, since: dt.date, today: dt.date, stage: Stage, steps) -> Card:
    with transaction.atomic():
        card = Card.objects.create(company_id=company_id, contact_id=contact_id, stage=stage, overdue_since=since)
        # day 1 = first day late; an old backlog starts its cadence today instead of all late at once
        day_one = max(since + dt.timedelta(days=1), today)
        Activity.objects.bulk_create(Activity(
            card=card, kind=s.kind, title=s.title, message=s.template,
            due_date=day_one + dt.timedelta(days=s.day - 1),
        ) for s in steps)
    return card


# Sync: open cards on the 1st day late, resolve the ones with nothing overdue

def sync_cards_service(*, today: dt.date | None = None) -> None:
    """Idempotent.
    ponytail: runs on each board load (no scheduler in the stack); move to a daily job if it gets slow."""
    today = today or timezone.localdate()
    overdue = {(r['company_id'], r['contact_id']): r['since']
               for r in _overdue(today).values('company_id', 'contact_id').annotate(since=Min('date'))}
    open_cards = {(c.company_id, c.contact_id): c for c in Card.objects.filter(closed_at__isnull=True)}  # type:ignore
    first = Stage.objects.filter(kind=StageKind.OPEN).first()
    resolved = Stage.objects.filter(kind=StageKind.RESOLVED).first()
    steps = list(CadenceStep.objects.filter(active=True))

    if first:
        for (company_id, contact_id), since in overdue.items():
            if (company_id, contact_id) in open_cards:
                continue
            try:
                _open_card(company_id, contact_id, since, today, first, steps)
            except IntegrityError:  # another request opened it meanwhile
                continue

    if resolved:
        paid_off = [c for key, c in open_cards.items() if key not in overdue and not _overdue_of(c, today).exists()]
        for card in paid_off:
            card.stage, card.closed_at, card.updated_at = resolved, today, timezone.now()
        Card.objects.bulk_update(paid_off, ['stage', 'closed_at', 'updated_at'])


def send_to_dunning_service(*, user: User, contact_id: int) -> list[Card]:
    """From the customer page: one card per company where they have late installments,
    whatever the start date. Already open cards are returned as they are."""
    today = timezone.localdate()
    companies = list_companies_service(user=user)
    late = (_late(today).filter(contact_id=contact_id, company__in=companies)
            .values('company_id').annotate(since=Min('date')))
    if not late:
        raise ValidationError('This customer has no overdue installments')
    first = Stage.objects.filter(kind=StageKind.OPEN).first()
    steps = list(CadenceStep.objects.filter(active=True))
    ids = []
    with pghistory.context(user=user.pk):
        for r in late:
            card = Card.objects.filter(company_id=r['company_id'], contact_id=contact_id, closed_at__isnull=True).first() \
                or _open_card(r['company_id'], contact_id, r['since'], today, first, steps)  # type:ignore
            ids.append(card.pk)
    return list(_cards_for(user, today).filter(pk__in=ids))


# Cards

def _cards_for(user: User, today: dt.date):
    overdue = _late(today).filter(company_id=OuterRef('company_id'), contact_id=OuterRef('contact_id'),
                                  date__gte=OuterRef('overdue_since'))
    pending = Activity.objects.filter(card=OuterRef('pk'), done_at__isnull=True)
    return (Card.objects.filter(company__in=list_companies_service(user=user))
            .select_related('company', 'contact', 'stage', 'assignee')
            .annotate(
                overdue_amount=Coalesce(Subquery(overdue.values('contact_id').annotate(s=Sum('amount')).values('s')),
                                        Value(ZERO), output_field=MONEY),
                overdue_count=Coalesce(Subquery(overdue.values('contact_id').annotate(n=Count('id')).values('n')), 0),
                next_activity=Subquery(pending.order_by('due_date').values('due_date')[:1]),
                late_activities=Coalesce(Subquery(pending.filter(due_date__lt=today).values('card')
                                                  .annotate(n=Count('id')).values('n')), 0),
            ))


def list_cards_service(*, user: User, assignee_id=None, company_id=None, search: str | None = None, closed_days: int = 30):
    """Open cards plus the ones closed in the last `closed_days` (resolved / legal columns)."""
    sync_cards_service()
    today = timezone.localdate()
    qs = _cards_for(user, today).filter(Q(closed_at__isnull=True) | Q(closed_at__gte=today - dt.timedelta(days=closed_days)))
    if assignee_id:
        qs = qs.filter(assignee_id=assignee_id)
    if company_id:
        qs = qs.filter(company_id__in=company_id)
    if search:
        qs = qs.filter(Q(contact__name__icontains=search) | Q(contact__company_name__icontains=search))
    return qs


def get_card_service(*, user: User, card_id: int) -> Card:
    return _cards_for(user, timezone.localdate()).get(pk=card_id)


def card_installments_service(*, user: User, card_id: int):
    card = get_card_service(user=user, card_id=card_id)
    return _overdue_of(card, timezone.localdate()).order_by('date', 'id')


def assignees_service():
    """Users who can work the funnel."""
    return [u for u in User.objects.filter(is_active=True).order_by('name', 'email') if has_permission(u, 'dunning', CHANGE)]


def update_card_service(*, user: User, card_id: int, **fields) -> Card:
    card = get_card_service(user=user, card_id=card_id)
    if 'assignee_id' in fields and fields['assignee_id'] is not None:
        if fields['assignee_id'] not in {u.pk for u in assignees_service()}:
            raise ValidationError('This user cannot be responsible for collections')
    with transaction.atomic(), pghistory.context(user=user.pk):
        if 'stage_id' in fields:
            _move(user, card, Stage.objects.get(pk=fields.pop('stage_id')))
        for field, value in fields.items():
            setattr(card, field, value)
        card.save()
    return get_card_service(user=user, card_id=card_id)


def _move(user: User, card: Card, stage: Stage) -> None:
    if card.closed_at:
        raise ValidationError('This card is closed')
    today = timezone.localdate()
    if stage.kind == StageKind.RESOLVED:
        if _overdue_of(card, today).exists():
            raise ValidationError('There are still overdue installments')
        card.closed_at = today
    elif stage.kind == StageKind.LEGAL:
        check_permission(user, 'legal', CREATE)
        # links all the open installments of the customer to the case (they leave the funnel)
        case = create_case_service(user=user, company_id=card.company_id, contact_id=card.contact_id,  # type:ignore
                                   summary=f'Encaminhado pelo funil de cobrança (em atraso desde {card.overdue_since:%d/%m/%Y}).')
        card.legal_case, card.closed_at = case, today
    card.stage = stage


# Activities

def _activity_for(user: User, activity_id: int) -> Activity:
    return Activity.objects.select_related('card').get(pk=activity_id, card__company__in=list_companies_service(user=user))


def list_activities_service(*, user: User, card_id: int):
    get_card_service(user=user, card_id=card_id)
    return Activity.objects.filter(card_id=card_id).select_related('done_by').order_by(F('done_at').desc(nulls_first=True), 'due_date', 'id')


def create_activity_service(*, user: User, card_id: int, **fields) -> Activity:
    card = get_card_service(user=user, card_id=card_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        return Activity.objects.create(card=card, **fields)


def update_activity_service(*, user: User, activity_id: int, done: bool | None = None, **fields) -> Activity:
    activity = _activity_for(user, activity_id)
    if done is True and not activity.done_at:
        activity.done_at, activity.done_by = timezone.now(), user
    elif done is False:
        activity.done_at, activity.done_by, activity.answered = None, None, None
    for field, value in fields.items():
        setattr(activity, field, value)
    with transaction.atomic(), pghistory.context(user=user.pk):
        activity.save()
    return activity


def delete_activity_service(*, user: User, activity_id: int) -> None:
    activity = _activity_for(user, activity_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        activity.delete()


def agenda_service(*, user: User, assignee_id=None, until: dt.date | None = None):
    """Pending activities of open cards up to a date (default today): the daily to-do list."""
    sync_cards_service()
    qs = (Activity.objects.filter(done_at__isnull=True, card__closed_at__isnull=True,
                                  card__company__in=list_companies_service(user=user),
                                  due_date__lte=until or timezone.localdate())
          .select_related('card__contact', 'card__company', 'card__assignee'))
    return qs.filter(card__assignee_id=assignee_id) if assignee_id else qs


# Productivity (PDF 10.4)

def productivity_service(*, user: User, start: dt.date, end: dt.date) -> dict:
    today = timezone.localdate()
    companies = list_companies_service(user=user)
    acts = Activity.objects.filter(card__company__in=companies)
    done = acts.filter(done_at__date__range=(start, end))
    pending = acts.filter(done_at__isnull=True, card__closed_at__isnull=True)
    rows: dict[int | None, dict] = {}

    def row(uid, name):
        return rows.setdefault(uid, {'user_id': uid, 'name': name, 'done': 0, 'messages': 0, 'calls': 0,
                                     'no_answer': 0, 'pending': 0, 'late': 0})
    for r in done.values('done_by', 'done_by__name', 'done_by__email', 'kind', 'answered').annotate(n=Count('id')):
        x = row(r['done_by'], r['done_by__name'] or r['done_by__email'] or '—')
        x['done'] += r['n']
        if r['kind'] in ('message', 'call'):
            x[f"{r['kind']}s"] += r['n']
        if r['answered'] is False:
            x['no_answer'] += r['n']
    for r in pending.values('card__assignee', 'card__assignee__name', 'card__assignee__email').annotate(
            n=Count('id'), late=Count('id', filter=Q(due_date__lt=today))):
        x = row(r['card__assignee'], r['card__assignee__name'] or r['card__assignee__email'] or 'Sem responsável')
        x['pending'] += r['n']
        x['late'] += r['late']

    cards = Card.objects.filter(company__in=companies)
    closed = cards.filter(closed_at__range=(start, end))
    return {
        'open_cards': cards.filter(closed_at__isnull=True).count(),
        'overdue_amount': _overdue(today).filter(company__in=companies).aggregate(s=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))['s'],
        'resolved': closed.filter(stage__kind=StageKind.RESOLVED).count(),
        'to_legal': closed.filter(stage__kind=StageKind.LEGAL).count(),
        'people': sorted(rows.values(), key=lambda x: x['name']),
    }


# Settings: stages and cadence

def save_stage_service(*, user: User, stage_id: int | None = None, **fields) -> Stage:
    stage = Stage.objects.get(pk=stage_id) if stage_id else Stage()
    for field, value in fields.items():
        setattr(stage, field, value)
    with transaction.atomic(), pghistory.context(user=user.pk):
        stage.save()
        _check_stages()
    return stage


def delete_stage_service(*, user: User, stage_id: int) -> None:
    stage = Stage.objects.get(pk=stage_id)
    if stage.cards.exists():
        raise ValidationError('This stage has cards')
    with transaction.atomic(), pghistory.context(user=user.pk):
        stage.delete()
        _check_stages()


def _check_stages() -> None:
    kinds = set(Stage.objects.values_list('kind', flat=True))
    if not {StageKind.OPEN, StageKind.RESOLVED} <= kinds:
        raise ValidationError('The funnel needs at least one open stage and one resolved stage')


def save_step_service(*, user: User, step_id: int | None = None, **fields) -> CadenceStep:
    step = CadenceStep.objects.get(pk=step_id) if step_id else CadenceStep()
    for field, value in fields.items():
        setattr(step, field, value)
    with transaction.atomic(), pghistory.context(user=user.pk):
        step.save()
    return step


def delete_step_service(*, user: User, step_id: int) -> None:
    with transaction.atomic(), pghistory.context(user=user.pk):
        CadenceStep.objects.get(pk=step_id).delete()


def update_config_service(*, start_date: dt.date | None) -> Config:
    config = Config.get()
    config.start_date = start_date
    config.save()
    return config
