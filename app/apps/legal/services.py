from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.companies.services import list_companies_service
from apps.finance.models import Contact, Transaction, TransactionStatus, TransactionType
from apps.legal.models import CaseComment, CaseStage, CollectionCase
from apps.users.models import User

MONEY = DecimalField(max_digits=16, decimal_places=2)
TEXT_FIELDS = ('client_company', 'contact_info', 'delivered', 'summary', 'drive_link', 'agreement')
AGREEMENT_STAGES = {CaseStage.AGREEMENT}


def _linked(status: str):
    q = Q(transactions__type=TransactionType.INFLOW, transactions__status=status)
    return Coalesce(Sum('transactions__amount', filter=q), Value(Decimal('0')), output_field=MONEY)


def _cases_for(user: User):
    return (CollectionCase.objects.filter(company__in=list_companies_service(user=user))
            .annotate(open_amount=_linked(TransactionStatus.PLANNED),  # still owed
                      received_amount=_linked(TransactionStatus.REALIZED))
            .select_related('company', 'contact'))


def _check(case: CollectionCase) -> None:
    if case.stage in AGREEMENT_STAGES and not case.agreement.strip():
        raise ValidationError('Describe the agreement or sentence (amount, installments, first due date)')


def _log(user: User, case: CollectionCase, text: str) -> None:
    CaseComment.objects.create(case=case, author=user, text=text)


def list_cases_service(*, user: User, stage=None, company_id=None, contact_id=None, search: str | None = None):
    qs = _cases_for(user)
    if stage:
        qs = qs.filter(stage__in=stage)
    if company_id:
        qs = qs.filter(company_id__in=company_id)
    if contact_id:
        qs = qs.filter(contact_id=contact_id)
    if search:
        qs = qs.filter(Q(contact__name__icontains=search) | Q(client_company__icontains=search)
                       | Q(summary__icontains=search))
    return qs


def get_case_service(*, user: User, case_id: int) -> CollectionCase:
    return _cases_for(user).get(pk=case_id)


def create_case_service(*, user: User, company_id: int, contact_id: int, **fields) -> CollectionCase:
    """Opens the case and links the customer's open (planned) inflows of that company."""
    company = list_companies_service(user=user).get(pk=company_id)
    if not Contact.objects.filter(pk=contact_id).exists():
        raise ValidationError('Contact does not exist')
    for field in TEXT_FIELDS:
        if field in fields:
            fields[field] = fields[field].strip()
    case = CollectionCase(company=company, contact_id=contact_id, created_by=user, **fields)
    _check(case)
    with transaction.atomic(), pghistory.context(user=user.pk):
        case.save()
        linked = Transaction.objects.filter(
            company=company, contact_id=contact_id, type=TransactionType.INFLOW,
            status=TransactionStatus.PLANNED, collection_case__isnull=True,
        ).update(collection_case=case)
        _log(user, case, f'Caso aberto em "{case.get_stage_display()}"; {linked} parcela(s) em aberto vinculada(s).')  # type:ignore
    return get_case_service(user=user, case_id=case.pk)


def update_case_service(*, user: User, case_id: int, **fields) -> CollectionCase:
    # ponytail: company/contact are immutable (the linked installments belong to them)
    case = get_case_service(user=user, case_id=case_id)
    old_stage = case.stage
    for field in TEXT_FIELDS:
        if field in fields:
            fields[field] = fields[field].strip()
    for field, value in fields.items():
        setattr(case, field, value)
    _check(case)
    with transaction.atomic(), pghistory.context(user=user.pk):
        case.save(update_fields=[*fields, 'updated_at'])
        if case.stage != old_stage:
            text = f'Etapa: {CaseStage(old_stage).label} → {CaseStage(case.stage).label}'
            if case.stage in AGREEMENT_STAGES:
                text += f'\nAcordo: {case.agreement}'
            _log(user, case, text)
    return get_case_service(user=user, case_id=case.pk)


def delete_case_service(*, user: User, case_id: int) -> None:
    # The linked installments are kept and go back to the DRE / cash flow (FK SET_NULL)
    case = get_case_service(user=user, case_id=case_id)
    with transaction.atomic(), pghistory.context(user=user.pk):
        case.delete()


def list_comments_service(*, user: User, case_id: int):
    return get_case_service(user=user, case_id=case_id).comments.select_related('author')


def add_comment_service(*, user: User, case_id: int, text: str) -> CaseComment:
    case = get_case_service(user=user, case_id=case_id)
    if not text.strip():
        raise ValidationError('Comment is empty')
    comment = CaseComment.objects.create(case=case, author=user, text=text.strip())
    CollectionCase.objects.filter(pk=case.pk).update(updated_at=comment.created_at)  # bubbles up in the list
    return comment


def case_transactions_service(*, user: User, case_id: int):
    case = get_case_service(user=user, case_id=case_id)
    return case.transactions.select_related('company', 'subgroup', 'account', 'contact').order_by('date', 'id')
