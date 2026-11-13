from ninja import ModelSchema, Schema

from apps.finance.models import Account


class CreateAccount(Schema):
    company_id: int
    name: str


class PatchAccount(Schema):
    name: str


class AccountOut(ModelSchema):
    class Meta:
        model = Account
        fields = ['id', 'company', 'name', 'created_at', 'updated_at']
