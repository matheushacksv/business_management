"""Financial investments (PDF section 8): company or personal money applied at an institution.

Applications/redemptions of company investments with an account become TRANSFER-group transactions
(cash moves, the DRE does not)."""

from decimal import Decimal

import pghistory
from django.db import models


class InvestmentKind(models.TextChoices):
    CDB = 'cdb', 'CDB'
    LCI_LCA = 'lci_lca', 'LCI/LCA'
    TREASURY = 'treasury', 'Tesouro Direto'
    FUND = 'fund', 'Fundo'
    STOCKS = 'stocks', 'Ações'
    SAVINGS = 'savings', 'Poupança'
    OTHER = 'other', 'Outro'


class Holder(models.TextChoices):
    COMPANY = 'company', 'Empresa'
    PERSONAL = 'personal', 'Pessoal'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Investment(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='investments')
    holder = models.CharField(max_length=10, choices=Holder.choices, default=Holder.COMPANY)
    institution = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=InvestmentKind.choices, default=InvestmentKind.CDB)
    description = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['institution', 'description', 'id']


class MovementKind(models.TextChoices):
    APPLICATION = 'application', 'Aplicação'
    REDEMPTION = 'redemption', 'Resgate'
    BALANCE = 'balance', 'Saldo atualizado'  # statement balance on that date: the difference is the yield


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Movement(models.Model):
    investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='movements')
    date = models.DateField()
    kind = models.CharField(max_length=12, choices=MovementKind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    notes = models.CharField(max_length=200, blank=True)
    # cash leg (company investments moved through an account); deleted with the movement
    transaction = models.OneToOneField('finance.Transaction', on_delete=models.PROTECT, null=True, blank=True,
                                       related_name='investment_movement')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'id']
        constraints = [models.CheckConstraint(condition=models.Q(amount__gte=Decimal('0')), name='movement_amount_not_negative')]
