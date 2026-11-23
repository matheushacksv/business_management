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
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.attachments.models import Attachment
from apps.attachments.services import MAX_SIZE
from apps.companies.models import Company
from apps.finance.models import Account, Contact, ContactKind, Invoice, InvoiceKind, Transaction, TransactionStatus, TransactionType
from apps.finance.services import check_customer
from apps.integrations.models import AsaasConfig, EventStatus, WebhookEvent
from apps.sales.models import Sale
from apps.users.models import User

BASE_URL = {True: 'https://api-sandbox.asaas.com/v3', False: 'https://api.asaas.com/v3'}
PAID = {'PAYMENT_RECEIVED', 'PAYMENT_CONFIRMED'}
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

def _customer_body(c: Contact | None) -> dict:
    if c is None:
        raise ValidationError('Venda sem cliente')
    if c.kind != ContactKind.CUSTOMER:
        raise ValidationError(f'"{c.name}" está cadastrado como fornecedor: mude para cliente e complete o cadastro')
    check_customer(c)  # everything the NFS-e needs
    return {
        'name': c.company_name or c.name, 'cpfCnpj': c.document, 'email': c.email,  # type:ignore
        'mobilePhone': re.sub(r'\D', '', c.phone)[-11:] or None, 'postalCode': c.postal_code,  # type:ignore
        'addressNumber': c.address_number, 'complement': c.address_complement or None,  # type:ignore
        'province': c.address_district or None, 'notificationDisabled': True,  # type:ignore
    }


def _customer(config: AsaasConfig, sale: Sale) -> str:
    """Found by CPF/CNPJ (then updated with the system's data) or created."""
    body = _customer_body(sale.contact)
    found = [x for x in request(config, 'GET', '/customers', cpfCnpj=body['cpfCnpj'])['data'] if not x.get('deleted')]
    if found:
        return request(config, 'POST', f'/customers/{found[0]["id"]}', body)['id']
    return request(config, 'POST', '/customers', body)['id']


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
        elif payload.get('event') == 'PAYMENT_UPDATED':
            event.status, event.message = _updated(payload['payment'])
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
    tx = Transaction.objects.select_related('company', 'contact', 'series', 'sale__product').filter(asaas_id=p['id']).first()
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
        if not found and p.get('customer'):  # customer data fixed in the system since the charge: Reprocess picks it up
            request(config, 'POST', f'/customers/{p["customer"]}', _customer_body(tx.contact))
        data = found[0] if found else request(config, 'POST', '/invoices', _invoice_body(config, tx, p))
        Invoice.objects.update_or_create(transaction=tx, kind=InvoiceKind.SERVICE, defaults={'asaas_id': data['id']})
    return EventStatus.PROCESSED, 'Parcela baixada; NFS-e solicitada'


def _updated(p: dict) -> tuple[str, str]:
    """Due date / value changed on Asaas: same on the open receivable."""
    tx = Transaction.objects.filter(asaas_id=p['id'], status=TransactionStatus.PLANNED).first()
    if tx is None:
        return EventStatus.IGNORED, 'Cobrança fora do sistema ou já baixada'
    date, amount = dt.date.fromisoformat(p['dueDate']), Decimal(str(p['value']))
    if (tx.date, tx.amount) == (date, amount):
        return EventStatus.IGNORED, 'Sem mudança'
    tx.date, tx.amount = date, amount
    with pghistory.context(source='asaas'):
        tx.save(update_fields=['date', 'amount', 'updated_at'])
    return EventStatus.PROCESSED, f'Vencimento {date:%d/%m/%Y}, valor {amount}'


def _invoice_body(config: AsaasConfig, tx: Transaction, p: dict) -> dict:
    sale = tx.sale
    if not config.service_name:  # Asaas requires the name even with the id
        raise ValidationError('Nome do serviço municipal da NFS-e não configurado (Integrações)')
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


def _attach_files(invoice: Invoice, i: dict) -> list[str]:
    """PDF + XML of the issued NFS-e as the invoice's attachments (public links on asaas.com)."""
    have, errors = {a.mime_type for a in invoice.attachments.all()}, []
    for key, ext, mime in (('pdfUrl', 'pdf', 'application/pdf'), ('xmlUrl', 'xml', 'application/xml')):
        if mime in have:  # Reprocess / redelivery
            continue
        url = i.get(key) or ''
        host = urllib.parse.urlparse(url).hostname or ''
        if not (url.startswith('https://') and (host == 'asaas.com' or host.endswith('.asaas.com'))):
            continue  # only Asaas links: the URL comes from the payload
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'gestao-empresarial'})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read(MAX_SIZE + 1)
        except (urllib.error.URLError, TimeoutError) as e:
            errors.append(f'{ext}: {getattr(e, "reason", e)}')
            continue
        if not data or len(data) > MAX_SIZE:
            errors.append(f'{ext}: tamanho inválido')
            continue
        name = f'NFS-e {invoice.number or invoice.asaas_id}.{ext}'
        Attachment.objects.create(content_type=ContentType.objects.get_for_model(Invoice), object_id=invoice.pk,
                                  file=ContentFile(data, name=name), name=name, mime_type=mime, size=len(data))
    return errors


def _invoice_update(i: dict) -> tuple[str, str]:
    invoice = Invoice.objects.filter(asaas_id=i['id']).first()
    if invoice is None:
        return EventStatus.IGNORED, 'NFS-e fora do sistema'
    status = i.get('status', '')
    with pghistory.context(source='asaas'):
        if status == 'AUTHORIZED':
            invoice.done, invoice.number = True, str(i.get('number') or '')
            invoice.issue_date = dt.date.fromisoformat(i.get('effectiveDate') or timezone.localdate().isoformat())
            invoice.save()
            errors = _attach_files(invoice, i)
            if errors:  # NF already marked issued; Reprocess retries the download
                return EventStatus.ERROR, 'NFS-e emitida, arquivo não baixado: ' + '; '.join(errors)
        elif status in ('ERROR', 'CANCELED'):
            invoice.done, invoice.issue_date = False, None
            invoice.notes = f'Asaas: {i.get("statusDescription") or status}'
        invoice.save()
    return EventStatus.PROCESSED, f'NFS-e {status}'
