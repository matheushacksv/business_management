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


DESCRIPTION_TEMPLATE = ('{percent}% referente a {reference} de {description}, nos termos do contrato de '
                        'prestação de serviços firmado em {contract_date}.')


class AsaasConfig(models.Model):
    """One Asaas account per company: charges for the sale's receivables; on payment (webhook) the
    receivable is settled and the NFS-e for `invoice_percent` of it is issued."""

    company = models.OneToOneField('companies.Company', on_delete=models.CASCADE, related_name='asaas')
    # ponytail: plain text in the DB, never returned by the API; encrypt at rest if the DB is shared
    api_key = models.CharField(max_length=300, blank=True)
    sandbox = models.BooleanField(default=True)
    webhook_token = models.CharField(max_length=60, unique=True)  # header asaas-access-token
    account = models.ForeignKey('finance.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    fine_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    interest_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # monthly
    invoice_percent = models.DecimalField(max_digits=5, decimal_places=2, default=50)
    service_id = models.CharField(max_length=20, blank=True)  # municipalServiceId
    service_name = models.CharField(max_length=200, blank=True)
    iss_rate = models.DecimalField(max_digits=5, decimal_places=2, default=3)
    description_template = models.TextField(default=DESCRIPTION_TEMPLATE)


class PhoneLine(models.Model):
    """API4COM user of a system user: calls go out through their Webphone (Chrome extension).
    The token is created from their API4COM login (the password is not kept)."""

    user = models.OneToOneField('users.User', on_delete=models.CASCADE, related_name='phone_line')
    email = models.EmailField()  # API4COM login
    # ponytail: plain text in the DB like the Asaas key, never returned by the API
    token = models.CharField(max_length=300)
    extension = models.CharField(max_length=20)
    webhook_secret = models.CharField(max_length=60, unique=True)  # in the webhook URL: API4COM does not sign
    valid = models.BooleanField(default=True)  # False after a 401 (password changed / token removed)
    updated_at = models.DateTimeField(auto_now=True)


class Call(models.Model):
    """Click-to-call to a contact, optionally for a dunning activity; the webhook fills in the outcome."""

    contact = models.ForeignKey('finance.Contact', on_delete=models.SET_NULL, null=True, related_name='calls')
    activity = models.ForeignKey('dunning.Activity', on_delete=models.SET_NULL, null=True, blank=True, related_name='calls')
    user = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    called = models.CharField(max_length=20)  # E.164
    external_id = models.CharField(max_length=60, blank=True)  # API4COM call id (webhook)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.PositiveIntegerField(null=True, blank=True)  # seconds of conversation
    hangup_cause = models.CharField(max_length=40, blank=True)
    record_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
