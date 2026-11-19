import json

from ninja import Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.integrations_dto import CredentialsOut, EventOut, PipedriveConfigIn, PipedriveConfigOut, WebhookResult
from apps.finance.models import SubGroup
from apps.integrations import services
from apps.integrations.models import PipedriveConfig, WebhookEvent
from apps.users.permissions import CHANGE, VIEW, require_permission

router = Router(tags=['Integrations'])


# Webhook: no session; HTTP Basic credentials set on the Pipedrive automation

@router.post('/webhooks/pipedrive/deal', auth=None, response={200: WebhookResult, 400: dict, 401: dict})
def pipedrive_deal_webhook(request):
    if not services.authenticate(request.headers.get('Authorization')):
        return 401, {'detail': 'Invalid credentials'}
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return 400, {'detail': 'Body must be JSON'}
    if not isinstance(payload, dict):
        return 400, {'detail': 'Body must be a JSON object'}
    # 200 even when the import fails: the error stays on the event for review / reprocessing
    return services.receive_deal_service(payload=payload)


# Admin: settings and event log ("users" module = admins only)

@router.get('/integrations/pipedrive', response=PipedriveConfigOut)
@require_permission('users', VIEW)
def get_pipedrive_config(request):
    return PipedriveConfig.get()


@router.put('/integrations/pipedrive', response=PipedriveConfigOut)
@require_permission('users', CHANGE)
def update_pipedrive_config(request, data: PipedriveConfigIn):
    config = PipedriveConfig.get()
    if data.subgroup_id is not None:
        SubGroup.objects.get(pk=data.subgroup_id)
    config.subgroup_id = data.subgroup_id
    config.save()
    return config


@router.post('/integrations/pipedrive/credentials', response=CredentialsOut)
@require_permission('users', CHANGE)
def generate_pipedrive_credentials(request):
    username, password = services.generate_credentials_service(user=request.user)
    return {'username': username, 'password': password}


@router.get('/integrations/events', response=list[EventOut])
@paginate(PageNumberPagination, page_size=50)
@require_permission('users', VIEW)
def list_events(request, status: str | None = None):
    qs = WebhookEvent.objects.all()
    return qs.filter(status=status) if status else qs


@router.post('/integrations/events/{event_id}/reprocess', response=EventOut)
@require_permission('users', CHANGE)
def reprocess_event(request, event_id: int):
    return services.reprocess_event_service(event_id=event_id)
