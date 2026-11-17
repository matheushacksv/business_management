from ninja import Query, Router

from api.schemas.legal_dto import (
    CaseFilters, CaseOut, CommentOut, CreateCase, CreateComment, PatchCase, StageOut,
)
from api.schemas.transactions_dto import TransactionOut
from apps.legal import services
from apps.legal.models import CaseStage
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Legal'])


def _clean(data) -> dict:
    fields = data.dict(exclude_unset=True, exclude_none=True)
    if 'drive_link' in fields:
        fields['drive_link'] = str(fields['drive_link'])
    return fields


@router.get('/collection-case/stages', response=list[StageOut])
@require_permission('legal', VIEW)
def list_stages_endpoint(request):
    return [{'value': s.value, 'label': s.label} for s in CaseStage]


@router.get('/collection-case', response=list[CaseOut])
@require_permission('legal', VIEW)
def list_cases_endpoint(request, filters: Query[CaseFilters]):
    # ponytail: no pagination, the kanban needs every card; paginate if cases reach the thousands
    return services.list_cases_service(user=request.user, **filters.dict())


@router.post('/collection-case', response={201: CaseOut})
@require_permission('legal', CREATE)
def create_case_endpoint(request, data: CreateCase):
    return 201, services.create_case_service(user=request.user, **_clean(data))


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
