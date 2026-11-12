from typing import Self

from ninja import ModelSchema, Schema
from pydantic import EmailStr, model_validator

from apps.users.models import User


class CreateUserDTO(Schema):
    email: EmailStr
    password: str
    repeat_password: str

    @model_validator(mode='after')
    def _validate_password(self) -> Self:
        if self.password != self.repeat_password:
            raise ValueError('passwords do not match')
        return self


class UserOut(ModelSchema):
    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'is_superuser', 'is_staff', 'is_active']
