"""API4COM: click-to-call from a dunning activity through the caller's Webphone (Chrome extension).

Each system user calls with their own API4COM token and extension. The admin connects a user with the
user's API4COM login (the admin sets those passwords on the invite); a never-expiring token is created and
the password is dropped. The outcome comes back on a per-user webhook URL holding a secret (API4COM does
not sign webhooks). A call answered with at least MIN_TALK seconds of conversation completes its activity.
"""

import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.companies.services import list_companies_service
from apps.dunning.models import Activity
from apps.finance.models import Contact
from apps.integrations.models import Call, EventStatus, PhoneLine, WebhookEvent
from apps.users.models import User

BASE_URL = 'https://api.api4com.com/api/v1'
GATEWAY = 'gestao-enriquecedor'
MIN_TALK = 15  # seconds: shorter = hung up / dropped, the activity stays open to call again  # our integration id on API4COM: webhook filter + call metadata
ERRORS = {401: 'token inválido (senha trocada ou token removido): conecte o usuário de novo',
          424: 'Webphone fechado ou offline: abra a extensão no Chrome e confira "Você está online"'}


# HTTP

def request(token: str | None, method: str, path: str, body: dict | None = None, **query) -> dict | list:
    url = BASE_URL + path + (f'?{urllib.parse.urlencode(query)}' if query else '')
    headers = {'Content-Type': 'application/json', 'User-Agent': 'gestao-empresarial'}
    if token:
        headers['Authorization'] = token
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:  # POST /calls waits for the Webphone
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            detail = (json.loads(e.read()).get('error') or {}).get('message', '')
        except (ValueError, AttributeError):
            detail = ''
        raise ValidationError('API4COM: ' + (ERRORS.get(e.code) or detail or f'HTTP {e.code}'), code=str(e.code))
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValidationError(f'API4COM indisponível: {getattr(e, "reason", e)}')


def _extension(token: str) -> str:
    found = request(token, 'GET', '/integrations', **{'filter[where][gateway]': 'sippulse'})
    username = found[0].get('metadata', {}).get('username') if found else None  # type:ignore
    if not username:  # the extension is created with the plan, after payment
        raise ValidationError('Usuário ainda sem ramal na API4COM')
    return str(username)


# Settings (admin)

def connect_line_service(*, user_id: int, email: str, password: str, webhook_base: str) -> PhoneLine:
    """Login → never-expiring token → extension → webhook. `webhook_base` + secret = the user's webhook URL."""
    user = User.objects.get(pk=user_id, is_active=True)
    login = request(None, 'POST', '/users/login', {'email': email.strip(), 'password': password})
    token = request(login['id'], 'POST', '/users/accessTokens', {'ttl': -1})['id']  # type:ignore
    line = PhoneLine.objects.filter(user=user).first() or PhoneLine(user=user, webhook_secret=secrets.token_urlsafe(32))
    line.email, line.token, line.extension, line.valid = email.strip(), token, _extension(token), True
    existing = request(token, 'GET', '/integrations', **{'filter[where][gateway]': GATEWAY})
    request(token, 'PATCH', '/integrations', {
        **({'id': existing[0]['id']} if existing else {}),  # type:ignore
        'gateway': GATEWAY, 'webhook': True, 'webhookConstraint': {'metadata': {'gateway': GATEWAY}},
        'metadata': {'webhookUrl': webhook_base + line.webhook_secret, 'webhookVersion': 'v1.8',
                     'webhookTypes': ['channel-answer', 'channel-hangup']},
    })
    line.save()
    return line


# Calls

def e164(phone: str) -> str:
    digits = re.sub(r'\D', '', phone or '')
    if len(digits) in (10, 11):  # DDD + number
        digits = '55' + digits
    if not 12 <= len(digits) <= 13:
        raise ValidationError('Telefone do cliente inválido: cadastre com DDD')
    return '+' + digits


def place_call_service(*, user: User, activity_id: int | None = None, contact_id: int | None = None) -> Call:
    """For a dunning activity (an answered call completes it) or straight to a contact."""
    activity = None
    if activity_id is not None:
        activity = Activity.objects.select_related('card__contact').get(
            pk=activity_id, card__company__in=list_companies_service(user=user))
        contact = activity.card.contact
    else:
        contact = Contact.objects.get(pk=contact_id)
    line = PhoneLine.objects.filter(user=user, valid=True).first()
    if line is None:
        raise ValidationError('Telefonia não conectada para o seu usuário (Integrações → API4COM)')
    call = Call.objects.create(contact=contact, activity=activity, user=user, called=e164(contact.phone))
    body = {'caller': line.extension, 'extension': line.extension, 'called': call.called,
            'metadata': {'gateway': GATEWAY, 'callRef': str(call.pk)}}
    try:
        try:
            request(line.token, 'POST', '/calls', body)
        except ValidationError as e:
            if e.code != '404':
                raise
            line.extension = body['caller'] = body['extension'] = _extension(line.token)  # extension changed
            line.save(update_fields=['extension', 'updated_at'])
            request(line.token, 'POST', '/calls', body)
    except ValidationError as e:
        call.delete()
        if e.code == '401':
            PhoneLine.objects.filter(pk=line.pk).update(valid=False)
        raise
    return call


# Webhook

def line_for(secret: str) -> PhoneLine | None:
    line = PhoneLine.objects.filter(webhook_secret=secret).select_related('user').first() if secret else None
    return line if line and hmac.compare_digest(secret, line.webhook_secret) else None


def receive_event_service(*, line: PhoneLine, payload: dict) -> WebhookEvent:
    event = WebhookEvent.objects.create(source='api4com', payload=payload, key=str(payload.get('id', ''))[:40])
    return process_event_service(event=event, line=line)


def _record_url(url) -> str:
    host = urllib.parse.urlparse(str(url or '')).hostname or ''
    return str(url) if str(url).startswith('https://') and (host == 'api4com.com' or host.endswith('.api4com.com')) else ''


def process_event_service(*, event: WebhookEvent, line: PhoneLine | None = None) -> WebhookEvent:
    p = event.payload
    ref = str((p.get('metadata') or {}).get('callRef', ''))
    call = Call.objects.filter(pk=ref).select_related('activity', 'user').first() if ref.isdigit() else None
    if call is None or (line and call.user_id != line.user_id) or (p.get('metadata') or {}).get('gateway') != GATEWAY:
        event.status, event.message = EventStatus.IGNORED, 'Chamada fora do sistema'
    else:
        now = timezone.now()
        answered = p.get('eventType') == 'channel-answer' or bool(p.get('answeredAt'))
        call.external_id = str(p.get('id', ''))[:60]
        if answered and not call.answered_at:
            call.answered_at = now
        if p.get('eventType') == 'channel-hangup':
            call.ended_at, call.duration = now, int(p.get('duration') or 0)
            call.hangup_cause = str(p.get('hangupCause', ''))[:40]
            call.record_url = _record_url(p.get('recordUrl')) or call.record_url
        activity = call.activity
        talked = call.ended_at and call.answered_at and (call.duration or 0) >= MIN_TALK
        with transaction.atomic(), pghistory.context(source='api4com', user=call.user_id):
            call.save()
            if talked and activity and not activity.done_at:
                activity.done_at, activity.done_by, activity.answered = now, call.user, True
                activity.save(update_fields=['done_at', 'done_by', 'answered'])
        event.status = EventStatus.PROCESSED
        event.message = f'{p.get("eventType")}{" · atendida" if answered else ""}'
    event.processed_at = timezone.now()
    event.save()
    return event
