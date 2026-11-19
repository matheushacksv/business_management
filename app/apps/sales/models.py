from decimal import Decimal

import pghistory
from django.contrib.contenttypes.fields import GenericRelation
from django.db import models
from django.db.models.functions import Lower


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Product(models.Model):
    """Product/service sold (e.g. Assessoria, Low Ticket). Configurable list."""

    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='unique_product_name_ci')]

    def __str__(self):
        return self.name


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Salesperson(models.Model):
    """Seller or delivery/advisory professional. May or may not have a login (user)."""

    name = models.CharField(max_length=120)
    user = models.OneToOneField(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='salesperson'
    )
    active = models.BooleanField(default=True)
    monthly_salary = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='unique_salesperson_name_ci')]

    def __str__(self):
        return self.name


class SaleStatus(models.TextChoices):
    ACTIVE = 'active', 'Ativa'
    COMPLETED = 'completed', 'Concluída'
    CANCELED = 'canceled', 'Cancelada'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Sale(models.Model):
    """A closed deal/contract. Selling is not receiving: receivables are linked Transactions."""

    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='sales')
    contact = models.ForeignKey(
        'finance.Contact', on_delete=models.PROTECT, null=True, blank=True, related_name='sales'
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True, related_name='sales')
    salesperson = models.ForeignKey(
        Salesperson, on_delete=models.PROTECT, null=True, blank=True, related_name='sales'
    )
    delivery_responsible = models.ForeignKey(
        Salesperson, on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries'
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=60, blank=True)
    payment_terms = models.CharField(max_length=120, blank=True)  # free text, e.g. "Entrada + 11 parcelas"
    installments_count = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=SaleStatus.choices, default=SaleStatus.ACTIVE)
    notes = models.TextField(blank=True)
    pipedrive_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)  # deal id (import dedupe)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    attachments = GenericRelation('attachments.Attachment')  # signed contract, etc.

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['company', 'date'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=Decimal('0')), name='sale_amount_positive'),
        ]

    def __str__(self):
        return f'{self.date} - {self.amount}'


class CommissionKind(models.TextChoices):
    SELLER = 'seller', 'Vendedor'
    ADVISOR = 'advisor', 'Assessor'
    SCHEDULING = 'scheduling', 'Agendamento'
    CRM = 'crm', 'Implementação de CRM'
    OTHER = 'other', 'Outro'


PERCENT_KINDS = {CommissionKind.SELLER, CommissionKind.ADVISOR}  # % of the sale after tax; the rest is a fixed value


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Commission(models.Model):
    """Who earns what on a sale. Due the month after the sale, whether the customer paid or not."""

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='commissions')
    salesperson = models.ForeignKey(Salesperson, on_delete=models.PROTECT, related_name='commissions')
    kind = models.CharField(max_length=12, choices=CommissionKind.choices)
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    fixed_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    description = models.CharField(max_length=120, blank=True)
    # Paid = linked to the outflow that paid it; the amount is frozen then (deleting the outflow reopens it)
    payment = models.ForeignKey(
        'finance.Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='commissions_paid'
    )
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sale__date', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class SalaryPayment(models.Model):
    """Fixed pay of one month. Amount frozen at payment; deleting the outflow reopens the month."""

    salesperson = models.ForeignKey(Salesperson, on_delete=models.PROTECT, related_name='salary_payments')
    month = models.DateField()  # due month (1st day), same as the commissions paid with it
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment = models.OneToOneField('finance.Transaction', on_delete=models.CASCADE, related_name='salary_payment')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint('salesperson', 'month', name='unique_salary_payment_month')]


class StatementShare(models.Model):
    """Public link to one monthly statement, opened with a password handed to the professional.
    Not history-tracked: it only holds a token and a password hash."""

    salesperson = models.ForeignKey(Salesperson, on_delete=models.CASCADE, related_name='statement_shares')
    month = models.DateField()  # due month (1st day)
    token = models.CharField(max_length=64, unique=True)
    password = models.CharField(max_length=128)  # Django hash, the plain one is shown once
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='+')  # its access scopes the link
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint('salesperson', 'month', name='unique_statement_share_month')]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Adjustment(models.Model):
    """Bonus (+) or deduction (−) of one month outside the sales: goal hit, advance to discount...
    Paid with the statement: bonuses as an outflow, deductions as a reversal (inflow) in the same subgroup."""

    salesperson = models.ForeignKey(Salesperson, on_delete=models.PROTECT, related_name='adjustments')
    month = models.DateField()  # due month (1st day)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=14, decimal_places=2)  # signed, never zero
    payment = models.ForeignKey(
        'finance.Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='adjustments_paid'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
