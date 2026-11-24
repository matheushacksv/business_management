from ninja import Router

from api.schemas.contacts_dto import ContactOut, ContactSummaryOut, CreateContact, MergeContacts, PatchContact
from apps.dunning.services import situations_service
from apps.finance import selectors, services
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, check_permission, has_permission, require_permission

router = Router(tags=['Contacts'])


@router.post('/contact', response={201: ContactOut})
@require_permission('contacts', CREATE)
def create_contact_endpoint(request, data: CreateContact):
    return 201, services.create_contact_service(**data.dict())


@router.get('/contact', response=list[ContactOut])
@require_permission('contacts', VIEW)
def list_contacts_endpoint(request, search: str | None = None):
    contacts = list(services.list_contacts_service(search=search))
    if has_permission(request.user, 'transactions', VIEW):  # the situation comes from the money
        situations = situations_service(user=request.user, contact_ids=[c.pk for c in contacts] if search else None)
        for c in contacts:
            c.situation = situations.get(c.pk)  # type:ignore
    return contacts


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


@router.get('/contact/{contact_id}/summary', response=ContactSummaryOut)
@require_permission('contacts', VIEW)
def contact_summary_endpoint(request, contact_id: int):
    """Totals for the contact page: sales (if the role sees sales) and money (if it sees transactions)."""
    money = has_permission(request.user, 'transactions', VIEW)
    summary = selectors.contact_summary_selector(
        user=request.user, contact_id=contact_id,
        sales=has_permission(request.user, 'sales', VIEW), money=money,
    )
    situation = situations_service(user=request.user, contact_ids=[contact_id]).get(contact_id) if money else None
    return {**summary, 'situation': situation}


@router.post('/contact/{contact_id}/merge', response=ContactOut)
@require_permission('contacts', CHANGE)
def merge_contacts_endpoint(request, contact_id: int, data: MergeContacts):
    """Fold duplicated contacts into this one (their transactions, sales, cases and files move here)."""
    check_permission(request.user, 'contacts', DELETE)  # the duplicates are deleted
    return services.merge_contacts_service(user=request.user, target_id=contact_id, source_ids=data.source_ids)
