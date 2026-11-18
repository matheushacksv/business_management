from typing import Self

from ninja import ModelSchema, Schema
from pydantic import EmailStr, model_validator

from apps.users.models import Role, User
from apps.users.permissions import permissions_for


class CreateUserDTO(Schema):
    email: EmailStr
    password: str
    repeat_password: str
    name: str = ''
    role: Role = Role.MANAGER
    company_ids: list[int] = []

    @model_validator(mode='after')
    def _validate_password(self) -> Self:
        if self.password != self.repeat_password:
            raise ValueError('passwords do not match')
        return self


class ChangePasswordDTO(Schema):
    current_password: str
    new_password: str
    repeat_password: str

    @model_validator(mode='after')
    def _validate_password(self) -> Self:
        if self.new_password != self.repeat_password:
            raise ValueError('passwords do not match')
        return self


class PatchUserDTO(Schema):
    name: str | None = None
    role: Role | None = None
    company_ids: list[int] | None = None


class UserOut(ModelSchema):
    company_ids: list[int]

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'role', 'is_superuser', 'is_active', 'joined_at', 'deactivated_at']

    @staticmethod
    def resolve_company_ids(obj: User) -> list[int]:
        return [c.pk for c in obj.companies.all()]


class MeOut(UserOut):
    is_admin: bool
    permissions: dict[str, list[str]]  # module -> allowed actions, for the frontend to hide buttons

    @staticmethod
    def resolve_permissions(obj: User) -> dict[str, list[str]]:
        return permissions_for(obj)
