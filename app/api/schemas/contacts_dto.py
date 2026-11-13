from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import EmailStr

from apps.finance.models import Contact


class CreateContact(Schema):
    name: str
    company_name: str = ''
    document: str = ''
    email: EmailStr | Literal[''] = ''
    phone: str = ''


class PatchContact(Schema):
    name: str | None = None
    company_name: str | None = None
    document: str | None = None
    email: EmailStr | Literal[''] | None = None
    phone: str | None = None


class ContactOut(ModelSchema):
    class Meta:
        model = Contact
        fields = ['id', 'name', 'company_name', 'document', 'email', 'phone', 'created_at', 'updated_at']
