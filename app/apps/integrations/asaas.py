"""Asaas: charges for a sale's receivables and, once paid (webhook), settlement + NFS-e.

Port of the team's local tool: one key per company (its CNPJ checked against the account), customer by
CPF/CNPJ with Asaas notifications off, BOLETO (boleto + Pix) with fine/interest, NFS-e of a % of each
paid charge. Every create is deduplicated (externalReference / invoice per payment) so retries are safe.
"""

import datetime as dt
import hmac
import json
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

import pghistory
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.companies.models import Company
from apps.finance.models import Account, Invoice, InvoiceKind, Transaction, TransactionStatus, TransactionType
from apps.integrations.models import AsaasConfig, EventStatus, WebhookEvent
from apps.sales.models import Sale
from apps.users.models import User

BASE_URL = {True: 'https://api-sandbox.asaas.com/v3', False: 'https://api.asaas.com/v3'}
PAID = {'PAYMENT_RECEIVED', 'PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED_IN_CASH'}
CENT = Decimal('0.01')


# HTTP

def request(config: AsaasConfig, method: str, path: str, body: dict | None = None, **query) -> dict:
    url = BASE_URL[config.sandbox] + path + (f'?{urllib.parse.urlencode(query)}' if query else '')
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None, headers={
        'access_token': config.api_key, 'Content-Type': 'application/json', 'User-Agent': 'gestao-empresarial',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            errors = json.loads(e.read()).get('errors') or []
        except ValueError:
            errors = []
        raise ValidationError('Asaas: ' + ('; '.join(x.get('description', '') for x in errors) or f'HTTP {e.code}'))
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValidationError(f'Asaas indisponível: {getattr(e, "reason", e)}')


def _config(company_id: int) -> AsaasConfig:
    config = AsaasConfig.objects.filter(company_id=company_id).exclude(api_key='').first()
    if config is None:
        raise ValidationError('Empresa sem integração com o Asaas')
    return config


# Settings

def save_config_service(*, company_id: int, api_key: str | None = None, account_id: int | None = None, **fields) -> AsaasConfig:
    company = Company.objects.get(pk=company_id)
    config = AsaasConfig.objects.filter(company=company).first() \
        or AsaasConfig(company=company, webhook_token=secrets.token_urlsafe(32))
    if account_id is not None and not Account.objects.filter(pk=account_id, company=company).exists():
        raise ValidationError('Conta de outra empresa')
    config.account_id = account_id  # type:ignore
    for field, value in fields.items():
        setattr(config, field, value.strip() if isinstance(value, str) else value)
    try:
        config.description_template.format(percent='', reference='', description='', contract_date='')
    except (KeyError, IndexError, ValueError):
        raise ValidationError('Modelo da descrição: use só {percent}, {reference}, {description} e {contract_date}')
    if api_key:
        config.api_key = api_key.strip()
    if config.api_key:  # the key must be the company's own account
        document = re.sub(r'\D', '', request(config, 'GET', '/myAccount/commercialInfo').get('cpfCnpj') or '')
        if document != company.cnpj:
            raise ValidationError(f'A chave é da conta {document or "?"}, não do CNPJ da empresa')
    config.save()
    return config


# Charges

def _customer(config: AsaasConfig, sale: Sale) -> str:
    c = sale.contact
    if c is None or not c.document:
        raise ValidationError('Cliente sem CPF/CNPJ')
    found = [x for x in request(config, 'GET', '/customers', cpfCnpj=c.document)['data'] if not x.get('deleted')]
    if found:
        return found[0]['id']
    if not (c.postal_code and c.address_number):
        raise ValidationError('Cliente sem CEP e número do endereço (necessários para a NFS-e)')
    return request(config, 'POST', '/customers', {
        'name': c.company_name or c.name, 'cpfCnpj': c.document, 'email': c.email or None,
        'mobilePhone': re.sub(r'\D', '', c.phone)[-11:] or None, 'postalCode': c.postal_code,
        'addressNumber': c.address_number, 'complement': c.address_complement or None,
        'notificationDisabled': True,
    })['id']


def _label(tx: Transaction) -> str:
    if tx.reference:
        return tx.reference
    if tx.series_id:  # type:ignore
        return f'parcela {tx.series_index}/{tx.series.count}'  # type:ignore
    return 'parcela única'


def create_charges_service(*, user: User, sale_id: int) -> int:
    """One charge per planned receivable still without one (each its own due date and value)."""
    from apps.sales.services import get_sale_service

    sale = get_sale_service(user=user, sale_id=sale_id)
    config = _config(sale.company_id)  # type:ignore
    pending = list(sale.receivables.filter(type=TransactionType.INFLOW, status=TransactionStatus.PLANNED, asaas_id='')
                   .select_related('series').order_by('date', 'id'))
    if not pending:
        raise ValidationError('Nenhuma parcela a receber sem cobrança')
    customer = _customer(config, sale)
    product = sale.product.name if sale.product else 'Prestação de serviços'  # type:ignore
    with pghistory.context(user=user.pk, source='asaas'):
        for tx in pending:
            ref = f'tx-{tx.pk}'
            found = request(config, 'GET', '/payments', externalReference=ref)['data']
            payment = found[0] if found else request(config, 'POST', '/payments', {
                'customer': customer, 'billingType': 'BOLETO', 'value': float(tx.amount),
                'dueDate': tx.date.isoformat(), 'description': f'{product} – {_label(tx)}'[:500],
                'externalReference': ref,
                'fine': {'value': float(config.fine_percent), 'type': 'PERCENTAGE'},
                'interest': {'value': float(config.interest_percent)},
            })
            # saved one by one: a failure halfway keeps what Asaas already has
            Transaction.objects.filter(pk=tx.pk).update(asaas_id=payment['id'])
    return len(pending)


def sync_charge(tx: Transaction, deleted: bool = False) -> None:
    """Due date / value edited, or receivable deleted, in the system: same on Asaas (only open charges)."""
    if not tx.asaas_id or tx.status != TransactionStatus.PLANNED:
        return
    config = _config(tx.company_id)  # type:ignore
    if deleted:
        request(config, 'DELETE', f'/payments/{tx.asaas_id}')
    else:
        request(config, 'POST', f'/payments/{tx.asaas_id}', {'dueDate': tx.date.isoformat(), 'value': float(tx.amount)})


# Webhook

def authenticate(token: str | None) -> bool:
    if not token:
        return False
    config = AsaasConfig.objects.filter(webhook_token=token).first()
    return config is not None and hmac.compare_digest(token, config.webhook_token)


def receive_event_service(*, payload: dict) -> WebhookEvent:
    item = payload.get('payment') or payload.get('invoice') or {}
    event = WebhookEvent.objects.create(source='asaas', payload=payload, key=str(item.get('id', ''))[:40])
    return process_event_service(event=event)


def process_event_service(*, event: WebhookEvent) -> WebhookEvent:
    """Never raises (Asaas pauses the queue after failures): the outcome goes to the event."""
    payload = event.payload
    try:
        if payload.get('event') in PAID:
            event.status, event.message = _paid(payload['payment'])
        elif str(payload.get('event', '')).startswith('INVOICE_'):
            event.status, event.message = _invoice_update(payload['invoice'])
        else:
            event.status, event.message = EventStatus.IGNORED, payload.get('event', '')
        payment_id = (payload.get('payment') or {}).get('id') or (payload.get('invoice') or {}).get('payment')
        tx = Transaction.objects.filter(asaas_id=payment_id).first() if payment_id else None
        event.sale_id = tx.sale_id if tx else None  # type:ignore
    except ValidationError as e:
        event.status, event.message = EventStatus.ERROR, '; '.join(e.messages)
    except (KeyError, TypeError) as e:
        event.status, event.message = EventStatus.ERROR, f'Payload inesperado: {e}'
    event.processed_at = timezone.now()
    event.save()
    return event


def _paid(p: dict) -> tuple[str, str]:
    tx = Transaction.objects.select_related('company', 'series', 'sale__product').filter(asaas_id=p['id']).first()
    if tx is None:
        return EventStatus.IGNORED, 'Cobrança fora do sistema'
    config = _config(tx.company_id)  # type:ignore
    with pghistory.context(source='asaas'):
        if tx.status == TransactionStatus.PLANNED:  # settled even if the NFS-e below fails (reprocess retries it)
            tx.status = TransactionStatus.REALIZED
            tx.date = dt.date.fromisoformat(p.get('clientPaymentDate') or p.get('paymentDate') or timezone.localdate().isoformat())
            tx.account_id = tx.account_id or config.account_id  # type:ignore
            tx.save(update_fields=['status', 'date', 'account', 'updated_at'])
        invoice = Invoice.objects.filter(transaction=tx, kind=InvoiceKind.SERVICE).first()
        if invoice and (invoice.asaas_id or invoice.done):
            return EventStatus.PROCESSED, 'Parcela baixada; NFS-e já existia'
        found = [i for i in request(config, 'GET', '/invoices', payment=p['id'])['data'] if i.get('status') != 'CANCELED']
        data = found[0] if found else request(config, 'POST', '/invoices', _invoice_body(config, tx, p))
        Invoice.objects.update_or_create(transaction=tx, kind=InvoiceKind.SERVICE, defaults={'asaas_id': data['id']})
    return EventStatus.PROCESSED, 'Parcela baixada; NFS-e solicitada'


def _invoice_body(config: AsaasConfig, tx: Transaction, p: dict) -> dict:
    sale = tx.sale
    if not (config.service_id or config.service_name):
        raise ValidationError('Serviço municipal da NFS-e não configurado')
    percent = config.invoice_percent.normalize()
    description = config.description_template.format(
        percent=f'{percent:f}'.replace('.', ','), reference=_label(tx).lower(),
        description=(sale.product.name if sale and sale.product else 'prestação de serviços'),  # type:ignore
        contract_date=(sale.date if sale else tx.date).strftime('%d/%m/%Y'),
    )
    body = {
        'payment': p['id'], 'serviceDescription': description, 'observations': '',
        'value': float((Decimal(str(p['value'])) * config.invoice_percent / 100).quantize(CENT)),
        'deductions': 0, 'effectiveDate': timezone.localdate().isoformat(),
        'municipalServiceName': config.service_name,
        'taxes': {'retainIss': False, 'iss': float(config.iss_rate), 'cofins': 0, 'csll': 0, 'inss': 0, 'ir': 0, 'pis': 0},
    }
    if config.service_id:
        body['municipalServiceId'] = config.service_id
    return body


def _invoice_update(i: dict) -> tuple[str, str]:
    invoice = Invoice.objects.filter(asaas_id=i['id']).first()
    if invoice is None:
        return EventStatus.IGNORED, 'NFS-e fora do sistema'
    status = i.get('status', '')
    with pghistory.context(source='asaas'):
        if status == 'AUTHORIZED':
            invoice.done, invoice.number = True, str(i.get('number') or '')
            invoice.issue_date = dt.date.fromisoformat(i.get('effectiveDate') or timezone.localdate().isoformat())
        elif status in ('ERROR', 'CANCELED'):
            invoice.done, invoice.issue_date = False, None
            invoice.notes = f'Asaas: {i.get("statusDescription") or status}'
        invoice.save()
    return EventStatus.PROCESSED, f'NFS-e {status}'
