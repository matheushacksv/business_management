"""Inbound integrations. Pipedrive: an automation posts the signed deal (person + deal fields) as JSON."""

from django.db import models


class PipedriveConfig(models.Model):
    """Single row. The webhook authenticates with HTTP Basic (username + password, stored hashed)
    and acts as `user` (company access and audit history)."""

    username = models.CharField(max_length=60, blank=True)
    password = models.CharField(max_length=128, blank=True)  # Django hash
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    subgroup = models.ForeignKey('finance.SubGroup', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')  # receivables

    @classmethod
    def get(cls) -> 'PipedriveConfig':
        return cls.objects.get_or_create(pk=1)[0]


class EventStatus(models.TextChoices):
    PROCESSED = 'processed', 'Processado'
    IGNORED = 'ignored', 'Ignorado'
    ERROR = 'error', 'Erro'


class WebhookEvent(models.Model):
    """Every authenticated delivery, raw: dedupe, debugging and reprocessing."""

    source = models.CharField(max_length=20, default='pipedrive')
    key = models.CharField(max_length=40, blank=True)  # deal id
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=EventStatus.choices, default=EventStatus.ERROR)
    message = models.TextField(blank=True)  # error, or warnings of a processed event
    sale = models.ForeignKey('sales.Sale', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at', '-id']
