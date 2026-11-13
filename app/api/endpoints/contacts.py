from ninja import Router

from api.schemas.contacts_dto import ContactOut, CreateContact, PatchContact
from apps.finance import services
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Contacts'])


@router.post('/contact', response={201: ContactOut})
@require_permission('contacts', CREATE)
def create_contact_endpoint(request, data: CreateContact):
    return 201, services.create_contact_service(**data.dict())


@router.get('/contact', response=list[ContactOut])
@require_permission('contacts', VIEW)
def list_contacts_endpoint(request, search: str | None = None):
    return services.list_contacts_service(search=search)


@router.get('/contact/{contact_id}', response=ContactOut)
@require_permission('contacts', VIEW)
def get_contact_endpoint(request, contact_id: int):
    return services.get_contact_service(contact_id=contact_id)


@router.patch('/contact/{contact_id}', response=ContactOut)
@require_permission('contacts', CHANGE)
def update_contact_endpoint(request, contact_id: int, data: PatchContact):
    return services.update_contact_service(
        contact_id=contact_id, **data.dict(exclude_unset=True, exclude_none=True)
    )


@router.delete('/contact/{contact_id}', response={204: None})
@require_permission('contacts', DELETE)
def delete_contact_endpoint(request, contact_id: int):
    services.delete_contact_service(contact_id=contact_id)
    return 204, None
