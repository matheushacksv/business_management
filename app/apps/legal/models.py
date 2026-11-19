import pghistory
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models


class CaseStage(models.TextChoices):
    """Kanban columns of the legal team, in order."""

    NEW = 'new', 'Nova Ação'
    STAND_BY = 'stand_by', 'Stand By'
    REQUESTED = 'requested', 'Solicitada ao Jurídico'
    FILED = 'filed', 'Ação Protocolada'
    IN_PROGRESS = 'in_progress', 'Em andamento'
    AGREEMENT = 'agreement', 'Acordo ou Sentença'
    AWAITING_JUDGE = 'awaiting_judge', 'Aguardando Juiz'
    DONE = 'done', 'Concluída'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class CollectionCase(models.Model):
    """Collection action against a defaulting customer.

    Planned inflows linked to a case (Transaction.collection_case) are uncertain money:
    they leave the DRE and the cash flow until received (realized).
    The form fields are required by the API; the DB accepts blanks for imported cases.
    """

    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='collection_cases')
    contact = models.ForeignKey('finance.Contact', on_delete=models.PROTECT, related_name='collection_cases')
    client_company = models.CharField(max_length=160, blank=True)  # "Empresa" of the customer
    contact_info = models.CharField(max_length=160, blank=True)  # "Contato": phone / e-mail / person
    delivered = models.TextField(blank=True)  # "O que foi entregue"
    proposal_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    summary = models.TextField(blank=True)  # "Resumo da situação do cliente"
    drive_link = models.URLField(max_length=500, blank=True)
    stage = models.CharField(max_length=20, choices=CaseStage.choices, default=CaseStage.NEW)
    agreement = models.TextField(blank=True)  # required from the "Acordo ou Sentença" stage on
    # Loss classification, apart from the stage: sent to legal is not the same as unrecoverable (PDF 15)
    unrecoverable_at = models.DateField(null=True, blank=True)
    unrecoverable_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')  # petitions, agreements, evidence

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f'Cobrança #{self.pk} - {self.contact}'


class CaseComment(models.Model):
    """Progress notes; stage changes are logged here too."""

    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
