from ninja import ModelSchema, Schema

from apps.finance.models import SubGroup, Group

class CreateSubgroup(Schema):
    name: str
    group: Group

class PatchSubgroup(Schema):
    name: str | None = None
    group: Group | None = None

class SubgroupOut(ModelSchema):
    class Meta:
        model = SubGroup
        fields = ['id', 'name', 'group', 'created_at', 'updated_at']
