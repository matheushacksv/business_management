from decimal import Decimal

import pghistory
from django.db import models

class Group(models.TextChoices):
    OPERATING_REVENUE = 'operating_revenue', 'Receitas Operacionais'
    NON_OPERATING_REVENUE = 'non_operating_revenue', 'Receitas Não Operacionais'
    VARIABLE_COSTS = 'variable_costs', 'Custos Variáveis'
    FIXED_COSTS = 'fixed_costs', 'Custos Fixos'
    NON_OPERATING_EXPENSES = 'non_operating_expenses', 'Despesas Não Operacionais'

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
}

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


class Contact(models.Model):
    name = models.CharField(max_length=160)
    company_name = models.CharField(max_length=160, blank=True)
    document = models.CharField(max_length=14, blank=True) # CPF or CNPJ
    email = models.EmailField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['company', 'date'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=Decimal('0')), name='transaction_amount_positive')
        ]

    @property
    def is_reversal(self) -> bool:
        return self.type != NATURAL_TYPE[self.subgroup.group]
