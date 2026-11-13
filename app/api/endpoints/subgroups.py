from ninja import Router

from api.schemas.subgroups_dto import CreateSubgroup, PatchSubgroup, SubgroupOut
from apps.finance import services
from apps.finance.models import Group

router = Router(tags=['Subgroups'])


@router.post('/subgroup', response={201: SubgroupOut})
def create_subgroup_endpoint(request, data: CreateSubgroup):
    return 201, services.create_subgroup_service(name=data.name, group=data.group)


@router.get('/subgroup', response=list[SubgroupOut])
def list_subgroup_endpoint(request, group: Group | None = None):
    return 200, services.list_subgroups_service(group=group)


@router.get('/subgroup/{subgroup_id}', response=SubgroupOut)
def get_subgroup_endpoint(request, subgroup_id: int):
    return 200, services.get_subgroup_service(subgroup_id)


@router.patch('/subgroup/{subgroup_id}', response=SubgroupOut)
def update_subgroup_endpoint(request, subgroup_id: int, data: PatchSubgroup):
    return 200, services.update_subgroup_service(subgroup_id=subgroup_id, **data.dict(exclude_unset=True))


@router.delete('/subgroup/{subgroup_id}', response={204: None})
def delete_subgroup_endpoint(request, subgroup_id: int):
    return 204, services.delete_subgroup_service(subgroup_id=subgroup_id)
