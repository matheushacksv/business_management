from django.db.models import Q
from ninja import Query, Router

from api.schemas.legal_dto import (
    AgreementIn, BrokenAgreementIn, CaseFilters, CaseOut, CheckOut, ChecklistItemIn, ChecklistItemOut, CommentOut, CreateCase, CreateComment,
    LegalConfigIO, LegalStageIn, LegalStageOut, PatchCase, PrefillOut, ResponsibleOut, SetCheck,
)
from api.schemas.transactions_dto import TransactionOut
from apps.legal import services
from apps.legal.models import ChecklistItem, LegalConfig, LegalStage
from apps.users.models import Role, User
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Legal'])


def _clean(data) -> dict:
    fields = data.dict(exclude_unset=True, exclude_none=True)
    if 'responsible_id' in data.dict(exclude_unset=True):  # null clears it
        fields['responsible_id'] = data.responsible_id
    if 'drive_link' in fields:
        fields['drive_link'] = str(fields['drive_link'])
    return fields


@router.get('/legal-stage', response=list[LegalStageOut])
@require_permission('legal', VIEW)
def list_stages_endpoint(request):
    return LegalStage.objects.all()


@router.post('/legal-stage', response={201: LegalStageOut})
@require_permission('legal', CHANGE)
def create_stage_endpoint(request, data: LegalStageIn):
    return 201, services.save_stage_service(user=request.user, **data.dict())


@router.patch('/legal-stage/{stage_id}', response=LegalStageOut)
@require_permission('legal', CHANGE)
def update_stage_endpoint(request, stage_id: int, data: LegalStageIn):
    return services.save_stage_service(user=request.user, stage_id=stage_id, **data.dict())


@router.delete('/legal-stage/{stage_id}', response={204: None})
@require_permission('legal', DELETE)
def delete_stage_endpoint(request, stage_id: int):
    services.delete_stage_service(user=request.user, stage_id=stage_id)
    return 204, None


@router.get('/collection-case', response=list[CaseOut])
@require_permission('legal', VIEW)
def list_cases_endpoint(request, filters: Query[CaseFilters]):
    # ponytail: no pagination, the kanban needs every card; paginate if cases reach the thousands
    return services.list_cases_service(user=request.user, **filters.dict())


@router.post('/collection-case', response={201: CaseOut})
@require_permission('legal', CREATE)
def create_case_endpoint(request, data: CreateCase):
    return 201, services.create_case_service(user=request.user, **_clean(data))


@router.get('/collection-case/prefill', response=PrefillOut)
@require_permission('legal', VIEW)
def prefill_endpoint(request, company_id: int, contact_id: int):
    """Suggested values for a new case, from the customer's sales, payments and collection attempts."""
    return services.prefill_service(user=request.user, company_id=company_id, contact_id=contact_id)


@router.get('/collection-case/responsibles', response=list[ResponsibleOut])
@require_permission('legal', VIEW)
def responsibles_endpoint(request):
    """Who can be the legal responsible: active legal-team users and admins."""
    users = User.objects.filter(is_active=True).filter(Q(role__in=[Role.LEGAL, Role.ADMIN]) | Q(is_superuser=True))
    return [{'id': u.pk, 'name': u.name or u.email} for u in users.order_by('name', 'email')]


# Checklist items: set up by the admin (users module)

@router.get('/legal-checklist-item', response=list[ChecklistItemOut])
@require_permission('legal', VIEW)
def list_checklist_items_endpoint(request):
    return ChecklistItem.objects.all()


@router.post('/legal-checklist-item', response={201: ChecklistItemOut})
@require_permission('users', CHANGE)
def create_checklist_item_endpoint(request, data: ChecklistItemIn):
    return 201, ChecklistItem.objects.create(**data.dict())


@router.put('/legal-checklist-item/{item_id}', response=ChecklistItemOut)
@require_permission('users', CHANGE)
def update_checklist_item_endpoint(request, item_id: int, data: ChecklistItemIn):
    item = ChecklistItem.objects.get(pk=item_id)
    for key, value in data.dict().items():
        setattr(item, key, value)
    item.save()
    return item


@router.delete('/legal-checklist-item/{item_id}', response={204: None})
@require_permission('users', CHANGE)
def delete_checklist_item_endpoint(request, item_id: int):
    ChecklistItem.objects.filter(pk=item_id).delete()
    return 204, None


@router.get('/collection-case/{case_id}', response=CaseOut)
@require_permission('legal', VIEW)
def get_case_endpoint(request, case_id: int):
    return services.get_case_service(user=request.user, case_id=case_id)


@router.patch('/collection-case/{case_id}', response=CaseOut)
@require_permission('legal', CHANGE)
def update_case_endpoint(request, case_id: int, data: PatchCase):
    return services.update_case_service(user=request.user, case_id=case_id, **_clean(data))


@router.delete('/collection-case/{case_id}', response={204: None})
@require_permission('legal', DELETE)
def delete_case_endpoint(request, case_id: int):
    services.delete_case_service(user=request.user, case_id=case_id)
    return 204, None


@router.get('/collection-case/{case_id}/comments', response=list[CommentOut])
@require_permission('legal', VIEW)
def list_comments_endpoint(request, case_id: int):
    return services.list_comments_service(user=request.user, case_id=case_id)


@router.post('/collection-case/{case_id}/comments', response={201: CommentOut})
@require_permission('legal', VIEW)  # anyone following the case may comment
def add_comment_endpoint(request, case_id: int, data: CreateComment):
    return 201, services.add_comment_service(user=request.user, case_id=case_id, text=data.text)


@router.get('/collection-case/{case_id}/transactions', response=list[TransactionOut])
@require_permission('legal', VIEW)
def case_transactions_endpoint(request, case_id: int):
    return services.case_transactions_service(user=request.user, case_id=case_id)


@router.get('/collection-case/{case_id}/checklist', response=list[CheckOut])
@require_permission('legal', VIEW)
def checklist_endpoint(request, case_id: int):
    return services.checklist_service(user=request.user, case_id=case_id)


@router.put('/collection-case/{case_id}/checklist/{item_id}', response=list[CheckOut])
@require_permission('legal', CHANGE)
def set_check_endpoint(request, case_id: int, item_id: int, data: SetCheck):
    return services.set_check_service(user=request.user, case_id=case_id, item_id=item_id, **data.dict())


@router.post('/collection-case/{case_id}/agreement', response=CaseOut)
@require_permission('legal', CHANGE)
def register_agreement_endpoint(request, case_id: int, data: AgreementIn):
    return services.register_agreement_service(user=request.user, case_id=case_id, **data.dict())


@router.post('/collection-case/{case_id}/broken-agreement', response=CaseOut)
@require_permission('legal', CHANGE)
def broken_agreement_endpoint(request, case_id: int, data: BrokenAgreementIn):
    return services.broken_agreement_service(user=request.user, case_id=case_id, stage_id=data.stage_id)


@router.get('/legal-config', response=LegalConfigIO)
@require_permission('legal', VIEW)
def get_legal_config_endpoint(request):
    return LegalConfig.get()


@router.put('/legal-config', response=LegalConfigIO)
@require_permission('legal', CHANGE)
def update_legal_config_endpoint(request, data: LegalConfigIO):
    config = LegalConfig.get()
    config.minimum_wage = data.minimum_wage
    config.save()
    return config
