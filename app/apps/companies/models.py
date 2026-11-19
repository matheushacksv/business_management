from decimal import Decimal

import pghistory
from django.db import models


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Company(models.Model):
    name = models.CharField(max_length=120)
    cnpj = models.CharField(max_length=14, unique=True)
    pipedrive_label = models.CharField(max_length=120, blank=True)  # option text of the deal's company field
    initial_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0')
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10'))  # % on revenue, base of commissions
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} - {self.cnpj}'
