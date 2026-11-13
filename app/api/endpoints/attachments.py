from typing import Literal

from django.http import FileResponse
from ninja import File, Form, Router
from ninja.files import UploadedFile

from api.schemas.attachments_dto import AttachmentOut
from apps.attachments import services

router = Router(tags=['Attachments'])

# Permissions follow the parent record (checked in the services)
TargetName = Literal['transaction', 'contact', 'invoice', 'sale']


@router.post('/attachment', response={201: AttachmentOut})
def upload_attachment_endpoint(
    request, target: Form[TargetName], target_id: Form[int], file: File[UploadedFile]
):
    return 201, services.upload_attachment_service(
        user=request.user, target=target, target_id=target_id, file=file
    )


@router.get('/attachment', response=list[AttachmentOut])
def list_attachments_endpoint(request, target: TargetName, target_id: int):
    return services.list_attachments_service(user=request.user, target=target, target_id=target_id)


@router.get('/attachment/{attachment_id}/download')
def download_attachment_endpoint(request, attachment_id: int):
    # ponytail: streamed through Django so every download is permission-checked;
    # switch to short-lived presigned URLs if file traffic gets heavy
    attachment = services.get_attachment_service(user=request.user, attachment_id=attachment_id)
    return FileResponse(
        attachment.file.open('rb'), as_attachment=True, filename=attachment.name,
        content_type=attachment.mime_type or 'application/octet-stream',
    )


@router.delete('/attachment/{attachment_id}', response={204: None})
def delete_attachment_endpoint(request, attachment_id: int):
    services.delete_attachment_service(user=request.user, attachment_id=attachment_id)
    return 204, None
