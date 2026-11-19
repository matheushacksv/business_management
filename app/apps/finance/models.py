from decimal import Decimal

import pghistory
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

class Group(models.TextChoices):
    OPERATING_REVENUE = 'operating_revenue', 'Receitas Operacionais'
    NON_OPERATING_REVENUE = 'non_operating_revenue', 'Receitas Não Operacionais'
    VARIABLE_COSTS = 'variable_costs', 'Custos Variáveis'
    FIXED_COSTS = 'fixed_costs', 'Custos Fixos'
    NON_OPERATING_EXPENSES = 'non_operating_expenses', 'Despesas Não Operacionais'
    # Money moved between companies of the group: hits each company's cash, never the DRE
    TRANSFER = 'transfer', 'Transferências entre empresas'

class TransactionType(models.TextChoices):
    INFLOW = 'inflow', 'Entrada'
    OUTFLOW = 'outflow', 'Saída'

class TransactionStatus(models.TextChoices):
    PLANNED = 'planned', 'Previsto'
    REALIZED = 'realized', 'Realizado'

NATURAL_TYPE: dict[str, str] = {
    Group.OPERATING_REVENUE: TransactionType.INFLOW,
    Group.NON_OPERATING_REVENUE: TransactionType.INFLOW,
    Group.VARIABLE_COSTS: TransactionType.OUTFLOW,
    Group.FIXED_COSTS: TransactionType.OUTFLOW,
    Group.NON_OPERATING_EXPENSES: TransactionType.OUTFLOW,
}  # TRANSFER has no natural type: each transfer has one leg of each

TRANSFER_SUBGROUP_NAME = 'Transferência entre empresas'

@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class SubGroup(models.Model):
    name = models.CharField(max_length=150)
    group = models.CharField(max_length=50, choices=Group.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group', 'name']
        constraints = [
            models.UniqueConstraint(fields=['group', 'name'], name='unique_subgroup_per_group')
        ]

    def __str__(self):
        return f'{self.get_group_display()} / {self.name}'  #type:ignore


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Contact(models.Model):
    name = models.CharField(max_length=160)
    company_name = models.CharField(max_length=160, blank=True)
    document = models.CharField(max_length=14, blank=True) # CPF or CNPJ
    email = models.EmailField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    pipedrive_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)  # person id
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['document'],
                condition=~models.Q(document=''),
                name='unique_contact_document',
            ),
        ]

    def __str__(self):
        return self.name

@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Account(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='accounts')
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_account_per_company')
        ]

    def __str__(self):
        return self.name

class SeriesKind(models.TextChoices):
    INSTALLMENT = 'installment', 'Parcelado'
    RECURRING = 'recurring', 'Recorrente'


class SeriesFrequency(models.TextChoices):
    MONTHLY = 'monthly', 'Mensal'


class TransactionSeries(models.Model):
    """Groups the occurrences of an installment plan or a recurring transaction."""

    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='series')
    kind = models.CharField(max_length=20, choices=SeriesKind.choices)
    frequency = models.CharField(max_length=20, choices=SeriesFrequency.choices, default=SeriesFrequency.MONTHLY)
    count = models.PositiveSmallIntegerField()
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)  # sum at creation time
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_kind_display()} x{self.count}'  # type:ignore


class Transfer(models.Model):
    """Money moved from one company of the group to another.

    The data lives in its two transactions (outflow in the source company, inflow in the
    destination), so cash flow, lists and filters see it like any transaction; the
    TRANSFER group keeps it out of the DRE. Both legs only change together.
    """

    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Transaction(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='transactions')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, null=True, blank=True, related_name='transactions')
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, null=True, blank=True, related_name='transactions')
    subgroup = models.ForeignKey(SubGroup, on_delete=models.PROTECT, related_name='transactions')
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    type = models.CharField(max_length=20, choices=TransactionType.choices)
    status = models.CharField(max_length=10, choices=TransactionStatus.choices, default=TransactionStatus.PLANNED)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    series = models.ForeignKey(
        TransactionSeries, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    series_index = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-based: "3/10"
    transfer = models.ForeignKey(  # one of the two legs of a transfer between companies
        Transfer, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions'
    )
    sale = models.ForeignKey(  # receivable of a sale
        'sales.Sale', on_delete=models.PROTECT, null=True, blank=True, related_name='receivables'
    )
    collection_case = models.ForeignKey(  # planned + linked = out of DRE / cash flow (uncertain)
        'legal.CollectionCase', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['company', 'date'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=Decimal('0')), name='transaction_amount_positive'),
            models.UniqueConstraint(fields=['series', 'series_index'], name='unique_series_index'),
        ]

    @property
    def is_reversal(self) -> bool:
        natural = NATURAL_TYPE.get(self.subgroup.group)
        return natural is not None and self.type != natural


class InvoiceKind(models.TextChoices):
    SERVICE = 'service', 'NF de Serviço'
    PRODUCT = 'product', 'NF de Produto'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Invoice(models.Model):
    """A required NF for a transaction.

    The row existing means "this transaction requires this NF". Direction comes from the
    transaction type: outflow -> NF to receive from the supplier, inflow -> NF to issue.
    """

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='invoices')
    kind = models.CharField(max_length=10, choices=InvoiceKind.choices, default=InvoiceKind.SERVICE)
    done = models.BooleanField(default=False)  # received (expense) / issued (revenue)
    number = models.CharField(max_length=60, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')

    class Meta:
        ordering = ['transaction__date', 'id']
        constraints = [
            models.UniqueConstraint(fields=['transaction', 'kind'], name='unique_invoice_kind_per_transaction'),
            # A done NF must have its date
            models.CheckConstraint(
                condition=models.Q(done=False) | models.Q(issue_date__isnull=False),
                name='invoice_done_requires_issue_date',
            ),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} #{self.number or "-"}'  # type:ignore

    @property
    def direction(self) -> str:
        return 'receive' if self.transaction.type == TransactionType.OUTFLOW else 'issue'
