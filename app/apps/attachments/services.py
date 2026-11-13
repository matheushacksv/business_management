from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models

from apps.attachments.models import Attachment
from apps.finance.models import Contact, Invoice, Transaction
from apps.finance.services import get_contact_service, get_invoice_service, get_transaction_service
from apps.sales.models import Sale
from apps.sales.services import get_sale_service
from apps.users.models import User
from apps.users.permissions import CHANGE, VIEW, check_permission

MAX_SIZE = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {
    '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.heic',   # receipts, boletos, scans
    '.xml',                                              # NF-e
    '.xlsx', '.xls', '.csv', '.doc', '.docx', '.txt',
}


@dataclass(frozen=True)
class Target:
    model: type[models.Model]
    module: str  # permission module of the parent record
    get: Callable[[User, int], models.Model]  # scoped getter: raises DoesNotExist if not visible


# Attachable records. Access to an attachment = access to its parent record.
TARGETS: dict[str, Target] = {
    'transaction': Target(Transaction, 'transactions',
                          lambda user, pk: get_transaction_service(user=user, transaction_id=pk)),
    'contact': Target(Contact, 'contacts', lambda user, pk: get_contact_service(contact_id=pk)),
    'invoice': Target(Invoice, 'transactions',
                      lambda user, pk: get_invoice_service(user=user, invoice_id=pk)),
    'sale': Target(Sale, 'sales', lambda user, pk: get_sale_service(user=user, sale_id=pk)),  # contract
}
_BY_MODEL = {t.model: t for t in TARGETS.values()}


def _target(name: str) -> Target:
    if name not in TARGETS:
        raise ValidationError(f'Invalid target: {name}')
    return TARGETS[name]


def _validate(file: UploadedFile) -> None:
    if Path(file.name or '').suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError(f'File type not allowed. Allowed: {", ".join(sorted(ALLOWED_EXTENSIONS))}')
    if not file.size:
        raise ValidationError('File is empty')
    if file.size > MAX_SIZE:
        raise ValidationError(f'File too large (max {MAX_SIZE // (1024 * 1024)} MB)')


def upload_attachment_service(*, user: User, target: str, target_id: int, file: UploadedFile) -> Attachment:
    spec = _target(target)
    check_permission(user, spec.module, CHANGE)
    parent = spec.get(user, target_id)
    _validate(file)
    return Attachment.objects.create(
        content_type=ContentType.objects.get_for_model(spec.model), object_id=parent.pk,
        file=file, name=Path(file.name or 'file').name[:255],
        mime_type=(file.content_type or '')[:100], size=file.size, uploaded_by=user,
    )


def list_attachments_service(*, user: User, target: str, target_id: int):
    spec = _target(target)
    check_permission(user, spec.module, VIEW)
    parent = spec.get(user, target_id)
    return Attachment.objects.filter(
        content_type=ContentType.objects.get_for_model(spec.model), object_id=parent.pk
    ).select_related('uploaded_by')


def _get_attachment(user: User, attachment_id: int, action: str) -> Attachment:
    attachment = Attachment.objects.select_related('content_type').get(pk=attachment_id)
    spec = _BY_MODEL[attachment.content_type.model_class()]
    check_permission(user, spec.module, action)
    spec.get(user, attachment.object_id)  # parent must be visible (company scope) -> else 404
    return attachment


def get_attachment_service(*, user: User, attachment_id: int) -> Attachment:
    return _get_attachment(user, attachment_id, VIEW)


def delete_attachment_service(*, user: User, attachment_id: int) -> None:
    _get_attachment(user, attachment_id, CHANGE).delete()  # stored file removed on commit (signal)
