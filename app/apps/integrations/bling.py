"""Bling: the product NF-e of each paid receivable (the half the Asaas NFS-e does not cover).

One Bling account per company (its own app, OAuth tokens refreshed here). The NF-e carries the sale's plan
handouts (Plan.nfe_skus, Bling product codes) splitting `percent` of the receivable equally; Bling computes
the taxes from the configured natureza de operação. Authorized → the invoice is done with number, PDF and XML.
Status changes also arrive by webhook (HMAC with the app's client secret).
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_DOWN, Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.finance.models import Contact, Invoice, InvoiceKind, Transaction, TransactionStatus
from apps.finance.services import check_customer
from apps.integrations.asaas import _label, attach_files
from apps.integrations.models import BlingConfig, EventStatus, WebhookEvent

API = 'https://api.bling.com.br/Api/v3'
OAUTH = 'https://bling.com.br/Api/v3/oauth'
CENT = Decimal('0.01')
AUTHORIZED, REFUSED, CANCELED = {5, 6}, {4: 'rejeitada', 9: 'denegada'}, 2


# HTTP / OAuth

def _call(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read()).get('error') or {}
        except ValueError:
            err = {}
        if isinstance(err, str):  # OAuth errors: {"error": "invalid_grant", ...}
            err = {'description': err}
        fields = '; '.join(f.get('msg', '') for f in err.get('fields') or [] if isinstance(f, dict))
        raise ValidationError('Bling: ' + (fields or err.get('description') or err.get('message') or f'HTTP {e.code}'))
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValidationError(f'Bling indisponível: {getattr(e, "reason", e)}')


def _token_request(config: BlingConfig, **form) -> None:
    basic = base64.b64encode(f'{config.client_id}:{config.client_secret}'.encode()).decode()
    data = _call(urllib.request.Request(f'{OAUTH}/token', method='POST', data=urllib.parse.urlencode(form).encode(), headers={
        'Authorization': f'Basic {basic}', 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': '1.0',
        'User-Agent': 'gestao-empresarial',
    }))
    config.access_token, config.refresh_token = data['access_token'], data['refresh_token']
    config.expires_at = timezone.now() + dt.timedelta(seconds=int(data.get('expires_in') or 21600))
    config.save()


def _access_token(company_id: int) -> str:
    """Refreshed one minute before it expires; the row lock keeps two refreshes from racing (the old refresh token dies)."""
    with transaction.atomic():
        config = BlingConfig.objects.select_for_update().filter(company_id=company_id).exclude(refresh_token='').first()
        if config is None:
            raise ValidationError('Empresa sem integração com o Bling autorizada')
        if not config.expires_at or config.expires_at < timezone.now() + dt.timedelta(minutes=1):
            try:
                _token_request(config, grant_type='refresh_token', refresh_token=config.refresh_token)
            except ValidationError:
                raise ValidationError('Bling: autorização expirou, clique em "Autorizar no Bling" (Integrações)')
        return config.access_token


def request(company_id: int, method: str, path: str, body: dict | None = None, **query) -> dict:
    url = API + path + (f'?{urllib.parse.urlencode(query)}' if query else '')
    return _call(urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={
        'Authorization': f'Bearer {_access_token(company_id)}', 'Content-Type': 'application/json',
        'User-Agent': 'gestao-empresarial',
    }))


# Settings (admin)

def save_config_service(*, company_id: int, client_id: str, client_secret: str | None = None, **fields) -> BlingConfig:
    config = BlingConfig.objects.filter(company_id=company_id).first() or BlingConfig(company_id=company_id)
    if client_id.strip() != config.client_id or client_secret:  # another app: authorize again
        config.access_token = config.refresh_token = ''
    config.client_id = client_id.strip()
    if client_secret:
        config.client_secret = client_secret.strip()
    for field, value in fields.items():
        setattr(config, field, value)
    config.save()
    return config


def authorize_url_service(*, company_id: int) -> str:
    config = BlingConfig.objects.filter(company_id=company_id).exclude(client_id='').exclude(client_secret='').first()
    if config is None:
        raise ValidationError('Informe o Client ID e o Client Secret do aplicativo e salve')
    config.state = secrets.token_urlsafe(32)
    config.save(update_fields=['state'])
    return f'{OAUTH}/authorize?' + urllib.parse.urlencode({'response_type': 'code', 'client_id': config.client_id, 'state': config.state})


def callback_service(*, code: str, state: str) -> BlingConfig:
    config = BlingConfig.objects.filter(state=state).first() if state else None
    if config is None or not hmac.compare_digest(state, config.state):
        raise ValidationError('Autorização do Bling inválida ou expirada: tente de novo')
    config.state = ''
    _token_request(config, grant_type='authorization_code', code=code)
    return config


def natures_service(*, company_id: int) -> list[dict]:
    return [{'id': n['id'], 'name': n.get('descricao', '')} for n in request(company_id, 'GET', '/naturezas-operacoes', limite=100)['data']
            if n.get('situacao', 1) == 1]


# Issuing

def _address(contact: Contact) -> dict:
    """Street / city / state from the CEP (the contact keeps only CEP, number, complement and district)."""
    cep = re.sub(r'\D', '', contact.postal_code)
    try:
        req = urllib.request.Request(f'https://viacep.com.br/ws/{cep}/json/', headers={'User-Agent': 'gestao-empresarial'})
        with urllib.request.urlopen(req, timeout=15) as r:
            found = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise ValidationError(f'Não foi possível consultar o CEP {cep}: tente de novo')
    if found.get('erro') or not found.get('localidade'):
        raise ValidationError(f'CEP {cep} não encontrado: corrija o cadastro do cliente')
    return {'endereco': found.get('logradouro') or contact.address_district, 'numero': contact.address_number,
            'complemento': contact.address_complement, 'bairro': contact.address_district or found.get('bairro', ''),
            'cep': cep, 'municipio': found['localidade'], 'uf': found.get('uf', '')}


def split(amount: Decimal, n: int) -> list[Decimal]:
    """Equal parts; the last one takes the leftover cents so the NF-e adds up exactly."""
    each = (amount / n).quantize(CENT, ROUND_DOWN)
    return [each] * (n - 1) + [amount - each * (n - 1)]


def _body(config: BlingConfig, invoice: Invoice) -> dict:
    tx = invoice.transaction
    sale, contact = tx.sale, tx.contact
    if not config.nature_id:
        raise ValidationError('Natureza de operação do Bling não configurada (Integrações)')
    if sale is None or sale.plan is None:  # type:ignore
        raise ValidationError('Venda sem plano: não dá para montar a NF-e de produto')
    skus = sale.plan.nfe_skus  # type:ignore
    if not skus:
        raise ValidationError(f'Plano "{sale.plan.name}" sem itens de NF-e (Vendas → Planos)')  # type:ignore
    if contact is None:
        raise ValidationError('Parcela sem cliente')
    check_customer(contact)
    amount = (tx.amount * config.percent / 100).quantize(CENT)
    return {
        'tipo': 1, 'dataOperacao': timezone.localtime().strftime('%Y-%m-%d %H:%M:%S'),
        'naturezaOperacao': {'id': config.nature_id},
        'contato': {'nome': contact.company_name or contact.name, 'numeroDocumento': contact.document,
                    'tipoPessoa': 'J' if len(contact.document) == 14 else 'F', 'contribuinte': 9,
                    'email': contact.email, 'telefone': contact.phone, 'endereco': _address(contact)},
        'itens': [{'codigo': sku, 'quantidade': 1, 'valor': float(v), 'tipo': 'P'} for sku, v in zip(skus, split(amount, len(skus)))],
        'observacoes': f'Referente a {_label(tx).lower()}.',
    }


def issue_service(*, invoice_id: int) -> Invoice:
    """Creates (once: the Bling id is kept) and sends the NF-e, then reads its status. Safe to call again."""
    invoice = Invoice.objects.select_related('transaction__sale__plan', 'transaction__contact', 'transaction__series').get(
        pk=invoice_id, kind=InvoiceKind.PRODUCT)
    if invoice.done:
        raise ValidationError('NF de produto já emitida')
    company_id = invoice.transaction.company_id  # type:ignore
    config = BlingConfig.objects.filter(company_id=company_id).first()
    if config is None:
        raise ValidationError('Empresa sem integração com o Bling')
    if not invoice.bling_id:
        invoice.bling_id = str(request(company_id, 'POST', '/nfe', _body(config, invoice))['data']['id'])
        invoice.save(update_fields=['bling_id', 'updated_at'])  # before sending: a retry never creates a second NF-e
    current = request(company_id, 'GET', f'/nfe/{invoice.bling_id}')['data']
    if current.get('situacao') not in AUTHORIZED:
        request(company_id, 'POST', f'/nfe/{invoice.bling_id}/enviar')
    return sync_service(invoice=invoice)


def sync_service(*, invoice: Invoice) -> Invoice:
    """Bling status → invoice: authorized = done with number, date, PDF and XML."""
    data = request(invoice.transaction.company_id, 'GET', f'/nfe/{invoice.bling_id}')['data']  # type:ignore
    status = data.get('situacao')
    with pghistory.context(source='bling'):
        if status in AUTHORIZED:
            invoice.done, invoice.number, invoice.notes = True, str(data.get('numero') or ''), ''
            invoice.issue_date = dt.date.fromisoformat((data.get('dataEmissao') or timezone.localdate().isoformat())[:10])
            invoice.save()
            errors = attach_files(invoice, [(data.get('linkPDF'), 'pdf', 'application/pdf'), (data.get('xml'), 'xml', 'application/xml')],
                                  'bling.com.br')
            if errors:
                invoice.notes = 'NF-e autorizada, arquivo não baixado: ' + '; '.join(errors)
        elif status in REFUSED or status == CANCELED:
            invoice.done, invoice.issue_date = False, None
            invoice.notes = f'Bling: NF-e {REFUSED.get(status, "cancelada")}, veja o motivo no Bling e emita de novo'
        else:
            invoice.notes = 'Bling: NF-e enviada, aguardando a SEFAZ'
        invoice.save()
    return invoice


def issue_on_payment(invoice: Invoice) -> None:
    """From the Asaas payment: issues when the company uses Bling; never raises (the reason stays on the invoice)."""
    if invoice.done or not BlingConfig.objects.filter(company_id=invoice.transaction.company_id).exclude(refresh_token='').exists():  # type:ignore
        return
    try:
        issue_service(invoice_id=invoice.pk)
    except ValidationError as e:
        Invoice.objects.filter(pk=invoice.pk).update(notes='; '.join(e.messages)[:1000])


def issue_on_realized(transaction_ids: list[int]) -> None:
    """Sale installment settled by hand: same product NF-e as an Asaas payment (sales whose plan has items only)."""
    txs = (Transaction.objects.filter(pk__in=transaction_ids, status=TransactionStatus.REALIZED, sale__plan__isnull=False)
           .exclude(sale__plan__nfe_skus=[]))
    for tx in txs:
        invoice, _ = Invoice.objects.get_or_create(transaction=tx, kind=InvoiceKind.PRODUCT)
        issue_on_payment(invoice)


# Webhook

def authenticate(company_id: int, body: bytes, signature: str | None) -> bool:
    config = BlingConfig.objects.filter(company_id=company_id).exclude(client_secret='').first()
    if config is None or not signature:
        return False
    expected = 'sha256=' + hmac.new(config.client_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def receive_event_service(*, company_id: int, payload: dict) -> WebhookEvent:
    data = payload.get('data') or {}
    event = WebhookEvent.objects.create(source='bling', payload=payload, key=str(data.get('id', ''))[:40])
    return process_event_service(event=event, company_id=company_id)


def process_event_service(*, event: WebhookEvent, company_id: int | None = None) -> WebhookEvent:
    """Only NF-e the system issued; the status is read from the API (the payload may be partial or out of order)."""
    key = event.key
    invoices = Invoice.objects.filter(bling_id=key, kind=InvoiceKind.PRODUCT).select_related('transaction') if key else Invoice.objects.none()
    if company_id is not None:
        invoices = invoices.filter(transaction__company_id=company_id)
    invoice = invoices.first()
    if invoice is None:
        event.status, event.message = EventStatus.IGNORED, 'NF-e fora do sistema'
    else:
        try:
            invoice = sync_service(invoice=invoice)
            event.status, event.message = EventStatus.PROCESSED, invoice.notes or f'NF-e {invoice.number} autorizada'
            event.sale_id = invoice.transaction.sale_id  # type:ignore
        except ValidationError as e:
            event.status, event.message = EventStatus.ERROR, '; '.join(e.messages)
    event.processed_at = timezone.now()
    event.save()
    return event
