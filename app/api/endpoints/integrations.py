import json
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from ninja import Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.integrations_dto import (
    AsaasConfigIn, AsaasConfigOut, BlingConfigIn, BlingConfigOut, BlingNatureOut, CallOut, ChargesOut, CredentialsOut,
    EventOut, PhoneLineIn, PhoneLineOut, PipedriveConfigIn, PipedriveConfigOut, UrlOut, WebhookResult,
)
from apps.companies.models import Company
from apps.companies.services import list_companies_service
from apps.finance.models import Invoice, SubGroup
from apps.integrations import api4com, asaas, bling, services
from apps.integrations.models import AsaasConfig, BlingConfig, Call, PhoneLine, PipedriveConfig, WebhookEvent
from apps.users.permissions import CHANGE, VIEW, check_permission, require_permission

router = Router(tags=['Integrations'])


# Webhook: no session; HTTP Basic credentials set on the Pipedrive automation

@router.post('/webhooks/pipedrive/deal', auth=None, response={200: WebhookResult, 400: dict, 401: dict})
# Pipedrive only accepts endpoint URLs ending in '/': same view on both paths
@router.post('/webhooks/pipedrive/deal/', auth=None, response={200: WebhookResult, 400: dict, 401: dict},
             include_in_schema=False, operation_id='pipedrive_deal_webhook_slash')
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
def list_events(request, status: str | None = None, source: str | None = None):
    qs = WebhookEvent.objects.all()
    if source:
        qs = qs.filter(source=source)
    return qs.filter(status=status) if status else qs


@router.post('/integrations/events/{event_id}/reprocess', response=EventOut)
@require_permission('users', CHANGE)
def reprocess_event(request, event_id: int):
    return services.reprocess_event_service(event_id=event_id)


# Asaas

@router.post('/webhooks/asaas', auth=None, response={200: WebhookResult, 400: dict, 401: dict})
def asaas_webhook(request):
    if not asaas.authenticate(request.headers.get('asaas-access-token')):
        return 401, {'detail': 'Invalid token'}
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return 400, {'detail': 'Body must be JSON'}
    if not isinstance(payload, dict):
        return 400, {'detail': 'Body must be a JSON object'}
    return asaas.receive_event_service(payload=payload)  # 200 even on error: Asaas pauses the queue otherwise


def _asaas_out(company: Company) -> dict:
    config = AsaasConfig.objects.filter(company=company).first() or AsaasConfig(company=company)
    return {
        'company_id': company.pk, 'company_name': company.name, 'has_key': bool(config.api_key),
        'sandbox': config.sandbox, 'webhook_token': config.webhook_token, 'account_id': config.account_id,
        **{f: getattr(config, f) for f in ('fine_percent', 'interest_percent', 'invoice_percent', 'service_id',
                                           'service_name', 'iss_rate', 'description_template')},
    }


@router.get('/integrations/asaas', response=list[AsaasConfigOut])
@require_permission('users', VIEW)
def list_asaas_configs(request):
    return [_asaas_out(c) for c in Company.objects.order_by('name')]


@router.put('/integrations/asaas/{company_id}', response=AsaasConfigOut)
@require_permission('users', CHANGE)
def update_asaas_config(request, company_id: int, data: AsaasConfigIn):
    config = asaas.save_config_service(company_id=company_id, **data.dict())
    return _asaas_out(config.company)


@router.post('/sale/{sale_id}/asaas-charges', response=ChargesOut, tags=['Sales'])
@require_permission('sales', CHANGE)
def create_asaas_charges(request, sale_id: int):
    check_permission(request.user, 'transactions', CHANGE)
    return {'created': asaas.create_charges_service(user=request.user, sale_id=sale_id)}


# API4COM (telephony)

@router.post('/webhooks/api4com/{secret}', auth=None, response={200: WebhookResult, 400: dict, 401: dict})
def api4com_webhook(request, secret: str):
    line = api4com.line_for(secret)
    if line is None:
        return 401, {'detail': 'Invalid token'}
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return 400, {'detail': 'Body must be JSON'}
    if not isinstance(payload, dict):
        return 400, {'detail': 'Body must be a JSON object'}
    return api4com.receive_event_service(line=line, payload=payload)


def _line_out(line: PhoneLine) -> dict:
    return {'user_id': line.user_id, 'name': line.user.name or line.user.email, 'email': line.email,  # type:ignore
            'extension': line.extension, 'valid': line.valid, 'updated_at': line.updated_at}


@router.get('/integrations/api4com', response=list[PhoneLineOut])
@require_permission('users', VIEW)
def list_phone_lines(request):
    return [_line_out(x) for x in PhoneLine.objects.select_related('user').order_by('user__name', 'user__email')]


@router.put('/integrations/api4com/{user_id}', response=PhoneLineOut)
@require_permission('users', CHANGE)
def connect_phone_line(request, user_id: int, data: PhoneLineIn):
    base = request.build_absolute_uri('/api/webhooks/api4com/')
    return _line_out(api4com.connect_line_service(user_id=user_id, webhook_base=base, **data.dict()))


@router.delete('/integrations/api4com/{user_id}', response={204: None})
@require_permission('users', CHANGE)
def disconnect_phone_line(request, user_id: int):
    PhoneLine.objects.filter(user_id=user_id).delete()
    return 204, None


@router.post('/dunning/activity/{activity_id}/call', response={201: CallOut}, tags=['Dunning'])
@require_permission('dunning', CHANGE)
def place_activity_call(request, activity_id: int):
    return 201, api4com.place_call_service(user=request.user, activity_id=activity_id)


@router.post('/contact/{contact_id}/call', response={201: CallOut}, tags=['Contacts'])
@require_permission('contacts', VIEW)
def place_contact_call(request, contact_id: int):
    return 201, api4com.place_call_service(user=request.user, contact_id=contact_id)


@router.get('/contact/{contact_id}/calls', response=list[CallOut], tags=['Contacts'])
@require_permission('contacts', VIEW)
def list_contact_calls(request, contact_id: int):
    return Call.objects.filter(contact_id=contact_id).select_related('activity', 'user')


@router.get('/call/{call_id}', response=CallOut, tags=['Contacts'])
def get_call(request, call_id: int):
    """Own calls only: the "Ligar" button polls it until the call ends."""
    return Call.objects.select_related('activity', 'user').get(pk=call_id, user=request.user)


# Bling (product NF-e)

@router.api_operation(['GET', 'HEAD'], '/webhooks/bling/{company_id}', auth=None, include_in_schema=False)
def bling_webhook_check(request, company_id: int):
    return {}  # Bling probes the URL before saving the webhook; events come by POST


@router.post('/webhooks/bling/{company_id}', auth=None, response={200: WebhookResult, 400: dict, 401: dict})
def bling_webhook(request, company_id: int):
    if not bling.authenticate(company_id, request.body, request.headers.get('X-Bling-Signature-256')):
        return 401, {'detail': 'Invalid signature'}
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return 400, {'detail': 'Body must be JSON'}
    if not isinstance(payload, dict):
        return 400, {'detail': 'Body must be a JSON object'}
    # ponytail: synced inline; Bling wants a 2xx within 5 s, queue it if the NF-e download gets slow
    return bling.receive_event_service(company_id=company_id, payload=payload)


@router.get('/integrations/bling/callback', auth=None, include_in_schema=False)
def bling_callback(request, code: str = '', state: str = ''):
    """Bling's redirect after the user authorizes the app: back to the settings screen."""
    try:
        bling.callback_service(code=code, state=state)
        result = 'ok'
    except ValidationError as e:
        result = '; '.join(e.messages)
    return redirect('/admin/integrations?' + urlencode({'tab': 'bling', 'bling': result}))


def _bling_out(company: Company) -> dict:
    c = BlingConfig.objects.filter(company=company).first() or BlingConfig(company=company)
    return {'company_id': company.pk, 'company_name': company.name, 'client_id': c.client_id, 'has_secret': bool(c.client_secret),
            'connected': bool(c.refresh_token), 'nature_id': c.nature_id, 'nature_name': c.nature_name, 'percent': c.percent}


@router.get('/integrations/bling', response=list[BlingConfigOut])
@require_permission('users', VIEW)
def list_bling_configs(request):
    return [_bling_out(c) for c in Company.objects.order_by('name')]


@router.put('/integrations/bling/{company_id}', response=BlingConfigOut)
@require_permission('users', CHANGE)
def update_bling_config(request, company_id: int, data: BlingConfigIn):
    return _bling_out(bling.save_config_service(company_id=company_id, **data.dict()).company)


@router.post('/integrations/bling/{company_id}/authorize', response=UrlOut)
@require_permission('users', CHANGE)
def authorize_bling(request, company_id: int):
    return {'url': bling.authorize_url_service(company_id=company_id)}


@router.get('/integrations/bling/{company_id}/natures', response=list[BlingNatureOut])
@require_permission('users', VIEW)
def bling_natures(request, company_id: int):
    return bling.natures_service(company_id=company_id)


@router.post('/invoice/{invoice_id}/bling', response=WebhookResult, tags=['Invoices'])
@require_permission('transactions', CHANGE)
def issue_bling_invoice(request, invoice_id: int):
    """Product NF-e via Bling (also re-sends a rejected one after it was fixed in Bling)."""
    companies = list_companies_service(user=request.user)
    Invoice.objects.get(pk=invoice_id, transaction__company__in=companies)
    invoice = bling.issue_service(invoice_id=invoice_id)
    return {'status': 'processed' if invoice.done else 'ignored', 'message': invoice.notes or f'NF-e {invoice.number} autorizada',
            'sale_id': invoice.transaction.sale_id}
