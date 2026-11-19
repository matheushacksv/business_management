import base64
import binascii
import datetime as dt
import hmac
import re
import secrets
from decimal import Decimal

import pghistory
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, ValidationError as PydanticError, field_validator

from apps.companies.models import Company
from apps.companies.services import normalize_cnpj
from apps.finance.models import Contact
from apps.finance.services import create_contact_service, parse_amount
from apps.integrations.models import EventStatus, PipedriveConfig, WebhookEvent
from apps.sales.models import CommissionKind, Product, Sale, Salesperson
from apps.sales.services import create_commission_service, create_sale_service, generate_receivables_service
from apps.users.models import User

SELLER_PERCENT = Decimal('10')


# Credentials (HTTP Basic, set on the Pipedrive automation)

def generate_credentials_service(*, user: User) -> tuple[str, str]:
    """New username + password (shown once); the integration acts as `user` from now on."""
    config = PipedriveConfig.get()
    username, password = f'pipedrive-{secrets.token_hex(3)}', secrets.token_urlsafe(24)
    config.username, config.password, config.user = username, make_password(password), user
    config.save()
    return username, password


def authenticate(header: str | None) -> bool:
    config = PipedriveConfig.get()
    if not (header and header.startswith('Basic ') and config.username and config.password):
        return False
    try:
        username, _, password = base64.b64decode(header[6:]).decode().partition(':')
    except (binascii.Error, UnicodeDecodeError):
        return False
    return hmac.compare_digest(username, config.username) and check_password(password, config.password)


# Payload: the JSON body built on the automation (all values may come as text)

class DealPayload(BaseModel):
    deal_id: int
    person_id: int | None = None
    person_name: str
    person_email: str = ''
    person_phone: str = ''
    client_document: str = ''
    company_document: str
    proposal_value: Decimal
    product: str = ''
    owner_name: str = ''
    installments: int | None = None
    payment_method: str = ''
    notes: str = ''
    signed_date: dt.date | None = None
    # receivables are generated only when the first installment date comes
    down_payment: Decimal = Decimal('0')
    down_payment_date: dt.date | None = None
    first_installment_date: dt.date | None = None

    @field_validator('proposal_value', 'down_payment', mode='before')
    @classmethod
    def money(cls, v):
        if v in (None, ''):
            return Decimal('0')
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        value = parse_amount(str(v))
        if value is None:
            raise ValueError(f'invalid amount: {v}')
        return value

    @field_validator('person_id', 'installments', 'signed_date', 'down_payment_date', 'first_installment_date', mode='before')
    @classmethod
    def blank_is_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if re.fullmatch(r'\d{2}/\d{2}/\d{4}', v):  # 19/11/2026
                d, m, y = v.split('/')
                return f'{y}-{m}-{d}'
        return v if v not in ('', None) else None

    @field_validator('person_name', 'person_email', 'person_phone', 'client_document', 'company_document',
                     'product', 'owner_name', 'payment_method', 'notes', mode='before')
    @classmethod
    def text(cls, v):
        return '' if v is None else str(v).strip()


# Processing

def receive_deal_service(*, payload: dict) -> WebhookEvent:
    event = WebhookEvent.objects.create(payload=payload, key=str(payload.get('deal_id', ''))[:40])
    return process_event_service(event=event)


def process_event_service(*, event: WebhookEvent) -> WebhookEvent:
    """Creates the customer (if new), the sale, the seller commission and, when the dates come, the
    receivables. Never raises: the outcome goes to the event (Pipedrive retries and disables
    webhooks that keep failing)."""
    try:
        data = DealPayload.model_validate(event.payload)
        existing = Sale.objects.filter(pipedrive_id=data.deal_id).first()
        if existing:
            event.status, event.sale, event.message = EventStatus.IGNORED, existing, 'Negócio já importado'
        else:
            event.sale, warnings = _import_deal(data)
            event.status, event.message = EventStatus.PROCESSED, '\n'.join(warnings)
    except PydanticError as e:
        event.status, event.message = EventStatus.ERROR, '; '.join(
            f'{".".join(map(str, err["loc"]))}: {err["msg"]}' for err in e.errors())
    except (ValidationError, ObjectDoesNotExist) as e:
        event.status, event.message = EventStatus.ERROR, '; '.join(getattr(e, 'messages', None) or [str(e)])
    event.processed_at = timezone.now()
    event.save()
    return event


def _import_deal(data: DealPayload) -> tuple[Sale, list[str]]:
    config = PipedriveConfig.get()
    user = config.user
    if user is None or not user.is_active:
        raise ValidationError('Integração sem usuário ativo: gere as credenciais novamente')
    company = Company.objects.filter(cnpj=normalize_cnpj(data.company_document)).first()
    if company is None:
        raise ValidationError(f'Nenhuma empresa com o CNPJ {data.company_document}')
    if data.proposal_value <= 0:
        raise ValidationError('Valor da proposta vazio')

    warnings = []
    with transaction.atomic(), pghistory.context(user=user.pk, source='pipedrive'):
        contact = _contact(data)
        product = None
        if data.product:
            product = Product.objects.filter(name__iexact=data.product).first() \
                or Product.objects.create(name=data.product)
        seller = Salesperson.objects.filter(name__iexact=data.owner_name).first() if data.owner_name else None
        if data.owner_name and seller is None:
            warnings.append(f'Vendedor "{data.owner_name}" não encontrado na Equipe: venda sem vendedor e sem comissão')
        sale = create_sale_service(
            user=user, company_id=company.pk, date=data.signed_date or timezone.localdate(), amount=data.proposal_value,
            contact_id=contact.pk, product_id=product.pk if product else None,
            salesperson_id=seller.pk if seller else None, payment_method=data.payment_method[:60],
            installments_count=data.installments, notes=data.notes, pipedrive_id=data.deal_id,
        )
        if seller:
            create_commission_service(user=user, sale_id=sale.pk, salesperson_id=seller.pk,
                                      kind=CommissionKind.SELLER, percent=SELLER_PERCENT)
        if data.first_installment_date:
            warnings += _receivables(user, sale, data, config)
    return sale, warnings


def _contact(data: DealPayload) -> Contact:
    """Pipedrive person id, then document, then e-mail; otherwise a new contact. Fills blanks."""
    document = normalize_cnpj(data.client_document)
    contact = (data.person_id and Contact.objects.filter(pipedrive_id=data.person_id).first()) \
        or (document and Contact.objects.filter(document=document).first()) \
        or (data.person_email and Contact.objects.filter(email__iexact=data.person_email).first()) \
        or create_contact_service(name=data.person_name, document=document, email=data.person_email, phone=data.person_phone)
    for field, value in (('pipedrive_id', data.person_id), ('document', document),
                         ('email', data.person_email.lower()), ('phone', data.person_phone)):
        if value and not getattr(contact, field):
            if field == 'document' and Contact.objects.filter(document=value).exclude(pk=contact.pk).exists():
                continue
            if field == 'pipedrive_id' and Contact.objects.filter(pipedrive_id=value).exclude(pk=contact.pk).exists():
                continue
            setattr(contact, field, value)
    contact.save()
    return contact


def _receivables(user: User, sale: Sale, data: DealPayload, config: PipedriveConfig) -> list[str]:
    if config.subgroup_id is None:  # type:ignore
        return ['Parcelas não geradas: defina o subgrupo das parcelas em Integrações']
    try:
        with transaction.atomic():
            generate_receivables_service(
                user=user, sale_id=sale.pk, subgroup_id=config.subgroup_id, first_date=data.first_installment_date,  # type:ignore
                installments=data.installments or 1, down_payment=data.down_payment,
                down_payment_date=data.down_payment_date,
            )
    except ValidationError as e:
        return [f'Parcelas não geradas: {"; ".join(e.messages)}']
    return []


def reprocess_event_service(*, event_id: int) -> WebhookEvent:
    return process_event_service(event=WebhookEvent.objects.get(pk=event_id))
