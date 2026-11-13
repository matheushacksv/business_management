from datetime import datetime

from ninja import ModelSchema

from apps.attachments.models import Attachment


class AttachmentOut(ModelSchema):
    target: str
    target_id: int
    uploaded_by_id: int | None
    created_at: datetime

    class Meta:
        model = Attachment
        fields = ['id', 'name', 'mime_type', 'size']

    @staticmethod
    def resolve_target(obj: Attachment) -> str:
        return obj.content_type.model

    @staticmethod
    def resolve_target_id(obj: Attachment) -> int:
        return obj.object_id
