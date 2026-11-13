from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.invoices_dto import (
    CreateInvoice,
    InvoiceOut,
    PatchInvoice,
    PendingInvoiceFilters,
    PendingInvoiceOut,
)
from apps.finance import services
from apps.users.permissions import CHANGE, VIEW, require_permission

# An invoice is part of its transaction: same permission module
router = Router(tags=['Invoices'])


@router.post('/invoice', response={201: InvoiceOut})
@require_permission('transactions', CHANGE)
def create_invoice_endpoint(request, data: CreateInvoice):
    return 201, services.create_invoice_service(user=request.user, **data.dict())


@router.get('/invoice', response=list[InvoiceOut])
@require_permission('transactions', VIEW)
def list_invoices_endpoint(request, transaction_id: int):
    return services.list_invoices_service(user=request.user, transaction_id=transaction_id)


@router.get('/invoice/pending', response=list[PendingInvoiceOut])
@paginate(PageNumberPagination, page_size=50)
@require_permission('transactions', VIEW)
def pending_invoices_endpoint(request, filters: Query[PendingInvoiceFilters]):
    return services.pending_invoices_service(user=request.user, **filters.dict())


@router.get('/invoice/{invoice_id}', response=InvoiceOut)
@require_permission('transactions', VIEW)
def get_invoice_endpoint(request, invoice_id: int):
    return services.get_invoice_service(user=request.user, invoice_id=invoice_id)


@router.patch('/invoice/{invoice_id}', response=InvoiceOut)
@require_permission('transactions', CHANGE)
def update_invoice_endpoint(request, invoice_id: int, data: PatchInvoice):
    return services.update_invoice_service(
        user=request.user, invoice_id=invoice_id, **data.dict(exclude_unset=True)
    )


@router.delete('/invoice/{invoice_id}', response={204: None})
@require_permission('transactions', CHANGE)
def delete_invoice_endpoint(request, invoice_id: int):
    services.delete_invoice_service(user=request.user, invoice_id=invoice_id)
    return 204, None
