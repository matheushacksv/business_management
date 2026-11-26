import pghistory
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models


class LegalStage(models.Model):
    """Configurable kanban column of the legal team. New cases enter the first one."""

    name = models.CharField(max_length=60)
    position = models.PositiveSmallIntegerField(default=0)
    requires_agreement = models.BooleanField(default=False)  # entering it needs the agreement/sentence text
    requires_checklist = models.BooleanField(default=False)  # entering it (from one without) needs the required checklist (PDF 11.2)
    requires_process_number = models.BooleanField(default=False)  # entering it needs the lawsuit number

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name


def first_stage() -> int | None:
    return LegalStage.objects.values_list('pk', flat=True).first()


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
    process_number = models.CharField(max_length=40, blank=True)  # lawsuit number, once filed
    stage = models.ForeignKey(LegalStage, on_delete=models.PROTECT, related_name='cases', default=first_stage)
    closed_at = models.DateField(null=True, blank=True)  # concluded: off the kanban, keeps its last stage
    agreement = models.TextField(blank=True)  # required by stages with requires_agreement
    # Loss classification, apart from the stage: sent to legal is not the same as unrecoverable (PDF 15)
    unrecoverable_at = models.DateField(null=True, blank=True)
    unrecoverable_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    responsible = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')  # legal
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


class AutoCheck(models.TextChoices):
    """Checklist items the system ticks by itself from data it already has."""
    CUSTOMER_DATA = 'customer_data', 'Cadastro do cliente completo'
    CONTRACT = 'contract', 'Contrato anexado na venda'
    AMOUNTS = 'amounts', 'Valores informados'
    ATTEMPTS = 'attempts', 'Tentativas de cobrança registradas'
    RESPONSIBLE = 'responsible', 'Responsável jurídico definido'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class ChecklistItem(models.Model):
    """What a case needs before it is filed (PDF 11.2), set up by the admin."""

    label = models.CharField(max_length=160)
    required = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)
    auto = models.CharField(max_length=20, choices=AutoCheck.choices, blank=True)  # blank: ticked by hand

    class Meta:
        ordering = ['position', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class CaseCheck(models.Model):
    """A manual item ticked on a case."""

    case = models.ForeignKey(CollectionCase, on_delete=models.CASCADE, related_name='checks')
    item = models.ForeignKey(ChecklistItem, on_delete=models.CASCADE, related_name='+')
    note = models.CharField(max_length=300, blank=True)
    checked_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['case', 'item'], name='unique_case_check')]
