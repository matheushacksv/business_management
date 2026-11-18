from decimal import Decimal

from ninja import ModelSchema, Schema
from pydantic import Field

from apps.companies.models import Company


class CompanyCreateDTO(Schema):
    name: str
    cnpj: str
    initial_balance: Decimal
    tax_rate: Decimal = Field(Decimal('10'), ge=0, le=100, max_digits=5, decimal_places=2)

class CompanyUpdateDTO(Schema):
    name: str | None = None
    cnpj: str | None = None
    initial_balance: Decimal | None = None
    tax_rate: Decimal | None = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)

class CompanyOut(ModelSchema):
    class Meta:
        model = Company
        fields = ['id', 'name', 'cnpj', 'initial_balance', 'tax_rate']
