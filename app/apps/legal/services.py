from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, DecimalField, Min, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.companies.services import list_companies_service
from apps.finance.models import Contact, Transaction, TransactionStatus, TransactionType
from apps.legal.models import AutoCheck, CaseCheck, CaseComment, ChecklistItem, CollectionCase, LegalStage
from apps.finance.services import add_months
from apps.users.models import User

MONEY = DecimalField(max_digits=16, decimal_places=2)
TEXT_FIELDS = ('client_company', 'contact_info', 'delivered', 'summary', 'drive_link', 'agreement')


def _linked(status: str, agreement: bool = True):
    q = Q(transactions__type=TransactionType.INFLOW, transactions__status=status, transactions__agreement_installment=agreement)
    return Coalesce(Sum('transactions__amount', filter=q), Value(Decimal('0')), output_field=MONEY)


def _cases_for(user: User):
    return (CollectionCase.objects.filter(company__in=list_companies_service(user=user))
            .annotate(open_amount=_linked(TransactionStatus.PLANNED),  # agreement installments still owed
                      received_amount=_linked(TransactionStatus.REALIZED),
                      defaulted_amount=_linked(TransactionStatus.PLANNED, agreement=False))  # suspended old ones
            .select_related('company', 'contact', 'stage', 'unrecoverable_by', 'responsible'))


def _check(case: CollectionCase) -> None:
    if case.stage.requires_agreement and not case.agreement.strip():
        raise ValidationError('Describe the agreement or sentence (amount, installments, first due date)')


def _log(user: User, case: CollectionCase, text: str) -> None:
    CaseComment.objects.create(case=case, author=user, text=text)


def list_cases_service(*, user: User, stage=None, company_id=None, contact_id=None, search: str | None = None):
    qs = _cases_for(user)
    if stage:
        qs = qs.filter(stage_id__in=stage)
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
    stage_id = fields.pop('stage_id', None)
    stage = LegalStage.objects.filter(pk=stage_id).first() if stage_id else LegalStage.objects.first()
    if stage is None:
        raise ValidationError('Etapa não existe')
    case = CollectionCase(company=company, contact_id=contact_id, stage=stage, created_by=user, **fields)
    _check(case)
    if stage.requires_checklist:
        raise ValidationError(f'Abra o caso numa etapa sem checklist obrigatório e complete o checklist antes de "{stage.name}"')
    with transaction.atomic(), pghistory.context(user=user.pk):
        case.save()
        linked = Transaction.objects.filter(
            company=company, contact_id=contact_id, type=TransactionType.INFLOW,
            status=TransactionStatus.PLANNED, collection_case__isnull=True,
        ).update(collection_case=case)
        _log(user, case, f'Caso aberto em "{stage.name}"; {linked} parcela(s) em aberto vinculada(s).')
    return get_case_service(user=user, case_id=case.pk)


def update_case_service(*, user: User, case_id: int, **fields) -> CollectionCase:
    # ponytail: company/contact are immutable (the linked installments belong to them)
    case = get_case_service(user=user, case_id=case_id)
    old_stage = case.stage
    unrecoverable = fields.pop('unrecoverable', None)
    closed = fields.pop('closed', None)
    log = []
    if closed is not None and closed != bool(case.closed_at):
        fields['closed_at'] = timezone.localdate() if closed else None
        log.append('Caso concluído' if closed else 'Caso reaberto')
    if 'stage_id' in fields and not LegalStage.objects.filter(pk=fields['stage_id']).exists():
        raise ValidationError('Etapa não existe')
    if unrecoverable is not None and unrecoverable != bool(case.unrecoverable_at):
        fields.update(unrecoverable_at=timezone.localdate() if unrecoverable else None,
                      unrecoverable_by=user if unrecoverable else None)
        log.append('Marcado como irrecuperável' if unrecoverable else 'Desmarcado como irrecuperável')
    for field in TEXT_FIELDS:
        if field in fields:
            fields[field] = fields[field].strip()
    if 'responsible_id' in fields and fields['responsible_id'] is not None \
            and not User.objects.filter(pk=fields['responsible_id'], is_active=True).exists():
        raise ValidationError('Responsável não existe')
    for field, value in fields.items():
        setattr(case, field, value)
    _check(case)
    if case.stage.requires_checklist and not old_stage.requires_checklist:
        missing = [c['label'] for c in checklist_service(user=user, case_id=case.pk, case=case) if c['required'] and not c['done']]
        if missing:
            raise ValidationError(f'Checklist incompleto: {"; ".join(missing)}')
    with transaction.atomic(), pghistory.context(user=user.pk):
        case.save(update_fields=[*fields, 'updated_at'])  # responsible_id: Django accepts the attname
        if case.stage != old_stage:
            text = f'Etapa: {old_stage.name} → {case.stage.name}'
            if case.stage.requires_agreement:
                text += f'\nAcordo: {case.agreement}'
            _log(user, case, text)
        for text in log:
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
    return case.transactions.filter(agreement_installment=True).select_related('company', 'subgroup', 'account', 'contact') \
        .order_by('date', 'id')



# Data the system already has: prefill of the legal form and automatic checklist items

def _overdue(company_id: int, contact_id: int):
    return Transaction.objects.filter(company_id=company_id, contact_id=contact_id, type=TransactionType.INFLOW,
                                      status=TransactionStatus.PLANNED, date__lt=timezone.localdate())


def prefill_service(*, user: User, company_id: int, contact_id: int) -> dict:
    from apps.dunning.models import Activity, ActivityKind
    from apps.sales.models import Sale, SaleStatus

    company = list_companies_service(user=user).get(pk=company_id)
    contact = Contact.objects.get(pk=contact_id)
    sales = list(Sale.objects.filter(company=company, contact=contact).exclude(status=SaleStatus.CANCELED)
                 .select_related('product').order_by('date'))
    received = Transaction.objects.filter(company=company, contact=contact, type=TransactionType.INFLOW,
                                          status=TransactionStatus.REALIZED).aggregate(t=Sum('amount'))['t']
    overdue = _overdue(company.pk, contact.pk).aggregate(t=Sum('amount'), n=Count('id'), since=Min('date'))
    done = Activity.objects.filter(card__company=company, card__contact=contact, done_at__isnull=False)
    summary = []
    if overdue['n']:
        total = f'{overdue["t"]:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        summary.append(f'{overdue["n"]} parcela(s) em atraso desde {overdue["since"]:%d/%m/%Y}, total R$ {total}.')
    if done.exists():
        counts = {k: done.filter(kind=k).count() for k in ActivityKind.values}
        parts = [f'{n} {ActivityKind(k).label.lower()}(s)' for k, n in counts.items() if n]
        silent = done.filter(answered=False).count()
        summary.append(f'Cobrança: {", ".join(parts)}' + (f', {silent} sem retorno' if silent else '') + '.')
    return {
        'client_company': contact.company_name,
        'contact_info': ' · '.join(v for v in (contact.phone, contact.email) if v),
        'delivered': '; '.join(f'{s.product.name if s.product else "Venda"} (contrato de {s.date:%d/%m/%Y})' for s in sales),
        'proposal_amount': sum((s.amount for s in sales), Decimal('0')) if sales else None,
        'paid_amount': received or Decimal('0'),
        'summary': ' '.join(summary),
    }


def _auto_done(case: CollectionCase) -> dict[str, bool]:
    from apps.attachments.models import Attachment
    from apps.dunning.models import Activity
    from apps.finance.services import check_customer
    from apps.sales.models import Sale, SaleStatus
    from django.contrib.contenttypes.models import ContentType

    try:
        check_customer(case.contact)
        customer_ok = True
    except ValidationError:
        customer_ok = False
    sale_ids = Sale.objects.filter(company_id=case.company_id, contact_id=case.contact_id) \
        .exclude(status=SaleStatus.CANCELED).values_list('pk', flat=True)  # type:ignore
    return {
        AutoCheck.CUSTOMER_DATA: customer_ok,
        AutoCheck.CONTRACT: Attachment.objects.filter(content_type=ContentType.objects.get_for_model(Sale),
                                                      object_id__in=list(sale_ids)).exists(),
        AutoCheck.AMOUNTS: case.proposal_amount is not None and case.paid_amount is not None,
        AutoCheck.ATTEMPTS: Activity.objects.filter(card__company_id=case.company_id, card__contact_id=case.contact_id,  # type:ignore
                                                    done_at__isnull=False).exists(),
        AutoCheck.RESPONSIBLE: case.responsible_id is not None,  # type:ignore
    }


def checklist_service(*, user: User, case_id: int, case: CollectionCase | None = None) -> list[dict]:
    case = case or get_case_service(user=user, case_id=case_id)
    auto = _auto_done(case)
    checks = {c.item_id: c for c in case.checks.select_related('checked_by')}  # type:ignore
    result = []
    for item in ChecklistItem.objects.filter(active=True):
        check = checks.get(item.pk)
        result.append({
            'item_id': item.pk, 'label': item.label, 'required': item.required, 'auto': item.auto or None,
            'done': (item.auto and auto[item.auto]) or check is not None,  # automatic ones can also be ticked by hand
            'note': check.note if check else '',
            'checked_by_name': (check.checked_by.name or check.checked_by.email) if check and check.checked_by else None,
            'checked_at': check.checked_at if check else None,
        })
    return result


def set_check_service(*, user: User, case_id: int, item_id: int, done: bool, note: str = '') -> list[dict]:
    case = get_case_service(user=user, case_id=case_id)
    item = ChecklistItem.objects.get(pk=item_id, active=True)
    with transaction.atomic(), pghistory.context(user=user.pk):
        if done:
            CaseCheck.objects.update_or_create(case=case, item=item, defaults={'note': note.strip(), 'checked_by': user})
            _log(user, case, f'Checklist: ✓ {item.label}' + (f' ({note.strip()})' if note.strip() else ''))
        elif CaseCheck.objects.filter(case=case, item=item).delete()[0]:
            _log(user, case, f'Checklist: desmarcado {item.label}')
    return checklist_service(user=user, case_id=case.pk, case=case)


# Stages (kanban columns)

def save_stage_service(*, user: User, stage_id: int | None = None, **fields) -> LegalStage:
    stage = LegalStage.objects.get(pk=stage_id) if stage_id else LegalStage()
    for field, value in fields.items():
        setattr(stage, field, value)
    with transaction.atomic(), pghistory.context(user=user.pk):
        stage.save()
    return stage


def delete_stage_service(*, user: User, stage_id: int) -> None:
    stage = LegalStage.objects.get(pk=stage_id)
    if stage.cases.filter(closed_at__isnull=True).exists():
        raise ValidationError('Esta etapa tem casos em andamento')
    other = LegalStage.objects.exclude(pk=stage_id).first()
    if other is None:
        raise ValidationError('O funil precisa de pelo menos uma etapa')
    with transaction.atomic(), pghistory.context(user=user.pk):
        stage.cases.update(stage=other)  # concluded cases keep a stage
        stage.delete()


# Agreement: its installments are the case's money (the defaulted ones stay suspended, out of it)

def _brl(v: Decimal) -> str:
    return 'R$ ' + f'{v:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def _drop_open_installments(case: CollectionCase) -> int:
    open_ = Transaction.objects.filter(collection_case=case, type=TransactionType.INFLOW, status=TransactionStatus.PLANNED,
                                       agreement_installment=True)
    charged = [t.reference or f'{t.date:%d/%m/%Y}' for t in open_.exclude(asaas_id='')]
    if charged:
        raise ValidationError(f'Cancele antes as cobranças do Asaas destas parcelas: {", ".join(charged)}')
    return open_.delete()[0]


def register_agreement_service(*, user: User, case_id: int, stage_id: int | None = None, text: str = '',
                               down_payment: Decimal | None = None, down_payment_date=None,
                               count: int, amount: Decimal, first_due) -> CollectionCase:
    case = get_case_service(user=user, case_id=case_id)
    stages = LegalStage.objects.filter(requires_agreement=True)
    stage = stages.filter(pk=stage_id).first() if stage_id else stages.first()
    if stage is None:
        raise ValidationError('Escolha uma etapa de acordo ou sentença')
    if down_payment and not down_payment_date:
        raise ValidationError('Informe a data da entrada')
    linked = Transaction.objects.filter(collection_case=case, type=TransactionType.INFLOW)
    subgroup_id = (linked.values_list('subgroup_id', flat=True).first()
                   or Transaction.objects.filter(company=case.company, contact=case.contact, type=TransactionType.INFLOW)
                   .values_list('subgroup_id', flat=True).order_by('-date').first())
    if subgroup_id is None:
        raise ValidationError('O cliente não tem lançamentos de entrada para usar como subgrupo')
    rows = [('Entrada', down_payment_date, down_payment)] if down_payment else []
    rows += [(f'{i + 1}/{count}', add_months(first_due, i), amount) for i in range(count)]
    total = sum(r[2] for r in rows)
    summary = (f'Entrada de {_brl(down_payment)} em {down_payment_date:%d/%m/%Y} + ' if down_payment else '') \
        + f'{count}x de {_brl(amount)} a partir de {first_due:%d/%m/%Y} (total {_brl(total)})'
    with transaction.atomic(), pghistory.context(user=user.pk):
        dropped = _drop_open_installments(case)
        Transaction.objects.bulk_create(
            Transaction(company=case.company, contact=case.contact, subgroup_id=subgroup_id, collection_case=case, agreement_installment=True,
                        type=TransactionType.INFLOW, status=TransactionStatus.PLANNED, date=date, amount=value, reference=ref)
            for ref, date, value in rows
        )
        old_stage = case.stage
        case.stage, case.agreement = stage, '\n'.join(filter(None, [summary, text.strip()]))
        case.save(update_fields=['stage', 'agreement', 'updated_at'])
        _log(user, case, f'Etapa: {old_stage.name} → {stage.name}\nAcordo: {case.agreement}'
                         + (f'\n{dropped} parcela(s) em aberto do acordo anterior substituída(s)' if dropped else ''))
    return get_case_service(user=user, case_id=case.pk)


def broken_agreement_service(*, user: User, case_id: int, stage_id: int) -> CollectionCase:
    """Customer defaulted on the agreement: its open installments are cancelled, the lawsuit goes on."""
    case = get_case_service(user=user, case_id=case_id)
    stage = LegalStage.objects.filter(pk=stage_id, requires_agreement=False).first()
    if stage is None:
        raise ValidationError('Escolha uma etapa sem acordo')
    with transaction.atomic(), pghistory.context(user=user.pk):
        dropped = _drop_open_installments(case)
        old_stage, previous = case.stage, case.agreement
        case.stage, case.agreement = stage, ''
        case.save(update_fields=['stage', 'agreement', 'updated_at'])
        _log(user, case, f'Acordo descumprido: {dropped} parcela(s) em aberto cancelada(s)\n'
                         f'Etapa: {old_stage.name} → {stage.name}' + (f'\nAcordo anterior: {previous}' if previous else ''))
    return get_case_service(user=user, case_id=case.pk)
