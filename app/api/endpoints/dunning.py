from ninja import Query, Router

from api.schemas.dunning_dto import (
    ActivityIn,
    ActivityOut,
    AgendaOut,
    AssigneeOut,
    CardFilters,
    CardOut,
    ConfigIO,
    InstallmentOut,
    NoteIn,
    NoteOut,
    PatchActivity,
    PatchCard,
    ProductivityOut,
    ProductivityParams,
    StageIn,
    StageOut,
    StepIn,
    StepOut,
)
from apps.dunning import services
from apps.dunning.models import CadenceStep, Config, Stage
from apps.users.permissions import CHANGE, DELETE, VIEW, require_permission

router = Router(tags=['Dunning'])


# Funnel

@router.get('/dunning/card', response=list[CardOut])
@require_permission('dunning', VIEW)
def list_cards_endpoint(request, filters: Query[CardFilters]):
    return services.list_cards_service(user=request.user, **filters.dict())


@router.post('/dunning/send/{contact_id}', response=list[CardOut])
@require_permission('dunning', CHANGE)
def send_to_dunning_endpoint(request, contact_id: int):
    return services.send_to_dunning_service(user=request.user, contact_id=contact_id)


@router.get('/dunning/card/{card_id}', response=CardOut)
@require_permission('dunning', VIEW)
def get_card_endpoint(request, card_id: int):
    return services.get_card_service(user=request.user, card_id=card_id)


@router.patch('/dunning/card/{card_id}', response=CardOut)
@require_permission('dunning', CHANGE)
def update_card_endpoint(request, card_id: int, data: PatchCard):
    fields = data.dict(exclude_unset=True)
    if fields.get('stage_id', ...) is None:
        fields.pop('stage_id', None)
    return services.update_card_service(user=request.user, card_id=card_id, **fields)


@router.get('/dunning/card/{card_id}/installments', response=list[InstallmentOut])
@require_permission('dunning', VIEW)
def card_installments_endpoint(request, card_id: int):
    return services.card_installments_service(user=request.user, card_id=card_id)


@router.get('/dunning/card/{card_id}/activities', response=list[ActivityOut])
@require_permission('dunning', VIEW)
def list_activities_endpoint(request, card_id: int):
    return services.list_activities_service(user=request.user, card_id=card_id)


@router.post('/dunning/card/{card_id}/activities', response={201: ActivityOut})
@require_permission('dunning', CHANGE)
def create_activity_endpoint(request, card_id: int, data: ActivityIn):
    return 201, services.create_activity_service(user=request.user, card_id=card_id, **data.dict())


@router.get('/dunning/card/{card_id}/notes', response=list[NoteOut])
@require_permission('dunning', VIEW)
def list_notes_endpoint(request, card_id: int):
    return services.list_notes_service(user=request.user, card_id=card_id)


@router.post('/dunning/card/{card_id}/notes', response={201: NoteOut})
@require_permission('dunning', CHANGE)
def add_note_endpoint(request, card_id: int, data: NoteIn):
    return 201, services.add_note_service(user=request.user, card_id=card_id, text=data.text)


@router.patch('/dunning/activity/{activity_id}', response=ActivityOut)
@require_permission('dunning', CHANGE)
def update_activity_endpoint(request, activity_id: int, data: PatchActivity):
    fields = data.dict(exclude_unset=True)
    for field in ('notes', 'due_date', 'title', 'message'):  # only `answered` may be nulled
        if fields.get(field, ...) is None:
            fields.pop(field)
    return services.update_activity_service(user=request.user, activity_id=activity_id, **fields)


@router.delete('/dunning/activity/{activity_id}', response={204: None})
@require_permission('dunning', CHANGE)
def delete_activity_endpoint(request, activity_id: int):
    services.delete_activity_service(user=request.user, activity_id=activity_id)
    return 204, None


@router.get('/dunning/agenda', response=list[AgendaOut])
@require_permission('dunning', VIEW)
def agenda_endpoint(request, assignee_id: int | None = None):
    return services.agenda_service(user=request.user, assignee_id=assignee_id)


@router.get('/dunning/assignees', response=list[AssigneeOut])
@require_permission('dunning', VIEW)
def assignees_endpoint(request):
    return services.assignees_service()


@router.get('/dunning/productivity', response=ProductivityOut)
@require_permission('dunning', VIEW)
def productivity_endpoint(request, params: Query[ProductivityParams]):
    return services.productivity_service(user=request.user, **params.dict())


# Settings

@router.get('/dunning/stage', response=list[StageOut])
@require_permission('dunning', VIEW)
def list_stages_endpoint(request):
    return Stage.objects.all()


@router.post('/dunning/stage', response={201: StageOut})
@require_permission('dunning', CHANGE)
def create_stage_endpoint(request, data: StageIn):
    return 201, services.save_stage_service(user=request.user, **data.dict())


@router.patch('/dunning/stage/{stage_id}', response=StageOut)
@require_permission('dunning', CHANGE)
def update_stage_endpoint(request, stage_id: int, data: StageIn):
    return services.save_stage_service(user=request.user, stage_id=stage_id, **data.dict())


@router.delete('/dunning/stage/{stage_id}', response={204: None})
@require_permission('dunning', DELETE)
def delete_stage_endpoint(request, stage_id: int):
    services.delete_stage_service(user=request.user, stage_id=stage_id)
    return 204, None


@router.get('/dunning/cadence', response=list[StepOut])
@require_permission('dunning', VIEW)
def list_steps_endpoint(request):
    return CadenceStep.objects.all()


@router.post('/dunning/cadence', response={201: StepOut})
@require_permission('dunning', CHANGE)
def create_step_endpoint(request, data: StepIn):
    return 201, services.save_step_service(user=request.user, **data.dict())


@router.patch('/dunning/cadence/{step_id}', response=StepOut)
@require_permission('dunning', CHANGE)
def update_step_endpoint(request, step_id: int, data: StepIn):
    return services.save_step_service(user=request.user, step_id=step_id, **data.dict())


@router.delete('/dunning/cadence/{step_id}', response={204: None})
@require_permission('dunning', DELETE)
def delete_step_endpoint(request, step_id: int):
    services.delete_step_service(user=request.user, step_id=step_id)
    return 204, None


@router.get('/dunning/config', response=ConfigIO)
@require_permission('dunning', VIEW)
def get_config_endpoint(request):
    return Config.get()


@router.put('/dunning/config', response=ConfigIO)
@require_permission('dunning', CHANGE)
def update_config_endpoint(request, data: ConfigIO):
    return services.update_config_service(**data.dict())
