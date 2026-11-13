import uuid
from pathlib import Path

import pghistory
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


def upload_to(instance: 'Attachment', filename: str) -> str:
    # Random stored name: the original name is kept in `name`, never used as a path
    now = timezone.now()
    ext = Path(filename).suffix.lower()
    return f'attachments/{instance.content_type.model}/{now:%Y/%m}/{uuid.uuid4().hex}{ext}'


@pghistory.track(pghistory.InsertEvent(), pghistory.DeleteEvent())
class Attachment(models.Model):
    """A file linked to any supported record (transaction, contact; later sale, contract...)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey('content_type', 'object_id')
    file = models.FileField(upload_to=upload_to, max_length=255)
    name = models.CharField(max_length=255)  # original filename, for display/download
    mime_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='attachments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return self.name


@receiver(post_delete, sender=Attachment)
def delete_stored_file(sender, instance: Attachment, **kwargs):
    # Also runs on cascades (GenericRelation). Only after commit, so a rollback keeps the file.
    name, storage = instance.file.name, instance.file.storage
    if name:
        transaction.on_commit(lambda: storage.delete(name))
