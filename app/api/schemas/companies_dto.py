from decimal import Decimal

from ninja import ModelSchema, Schema

from apps.companies.models import Company


class CompanyCreateDTO(Schema):
    name: str
    cnpj: str
    initial_balance: Decimal

class CompanyUpdateDTO(Schema):
    name: str | None = None
    cnpj: str | None = None
    initial_balance: Decimal | None = None

class CompanyOut(ModelSchema):
    class Meta:
        model = Company
        fields = ['id', 'name', 'cnpj', 'initial_balance']
