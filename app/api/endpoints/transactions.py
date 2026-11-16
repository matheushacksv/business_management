from django.http import HttpResponse
from django.utils import timezone
from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.transactions_dto import (
    CreateSeries,
    CreateTransaction,
    CreateTransfer,
    PatchSeries,
    PatchTransaction,
    PatchTransfer,
    SeriesChangeOut,
    SeriesOut,
    TransactionFilters,
    TransactionOut,
    TransferOut,
)
from apps.finance import services
from apps.finance.exporter import XLSX_CONTENT_TYPE, transactions_xlsx
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Transactions'])


@router.post('/transaction', response={201: TransactionOut})
@require_permission('transactions', CREATE)
def create_transaction_endpoint(request, data: CreateTransaction):
    return 201, services.create_transaction_service(user=request.user, **data.dict())


@router.get('/transaction', response=list[TransactionOut])
@paginate(PageNumberPagination, page_size=50)
@require_permission('transactions', VIEW)
def list_transactions_endpoint(request, filters: Query[TransactionFilters]):
    return services.list_transactions_service(user=request.user, **filters.dict())


@router.get('/transaction/export')
@require_permission('transactions', VIEW)
def export_transactions_endpoint(request, filters: Query[TransactionFilters]):
    """Excel file with every transaction matching the filters (same ones as the list)."""
    qs = services.list_transactions_service(user=request.user, **filters.dict()).select_related('series')
    response = HttpResponse(transactions_xlsx(qs), content_type=XLSX_CONTENT_TYPE)
    filename = f'lancamentos-{timezone.localdate():%Y-%m-%d}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@router.get('/transaction/{transaction_id}', response=TransactionOut)
@require_permission('transactions', VIEW)
def get_transaction_endpoint(request, transaction_id: int):
    return services.get_transaction_service(user=request.user, transaction_id=transaction_id)


@router.patch('/transaction/{transaction_id}', response=TransactionOut)
@require_permission('transactions', CHANGE)
def update_transaction_endpoint(request, transaction_id: int, data: PatchTransaction):
    return services.update_transaction_service(
        user=request.user, transaction_id=transaction_id, **data.dict(exclude_unset=True)
    )


@router.delete('/transaction/{transaction_id}', response={204: None})
@require_permission('transactions', DELETE)
def delete_transaction_endpoint(request, transaction_id: int):
    services.delete_transaction_service(user=request.user, transaction_id=transaction_id)
    return 204, None


# Series (installments / recurring)

def _series_out(user, series_id: int) -> dict:
    series = services.get_series_service(user=user, series_id=series_id)
    transactions = services.series_transactions_service(user=user, series_id=series_id)
    return {**{f: getattr(series, f) for f in (
        'id', 'kind', 'frequency', 'count', 'total_amount', 'company_id', 'created_by_id', 'created_at'
    )}, 'transactions': list(transactions)}


@router.post('/transaction-series', response={201: SeriesOut})
@require_permission('transactions', CREATE)
def create_series_endpoint(request, data: CreateSeries):
    series = services.create_series_service(user=request.user, **data.dict())
    return 201, _series_out(request.user, series.pk)


@router.get('/transaction-series/{series_id}', response=SeriesOut)
@require_permission('transactions', VIEW)
def get_series_endpoint(request, series_id: int):
    return _series_out(request.user, series_id)


@router.patch('/transaction-series/{series_id}', response=SeriesChangeOut)
@require_permission('transactions', CHANGE)
def update_series_endpoint(request, series_id: int, data: PatchSeries, from_index: int = 1):
    """Apply the change to occurrence `from_index` and all the following ones."""
    affected = services.update_series_service(
        user=request.user, series_id=series_id, from_index=from_index, **data.dict(exclude_unset=True)
    )
    return {'affected': affected}


@router.delete('/transaction-series/{series_id}', response=SeriesChangeOut)
@require_permission('transactions', DELETE)
def cancel_series_endpoint(request, series_id: int, from_index: int = 1):
    """Delete the PLANNED occurrences from `from_index` on; realized ones are kept."""
    return {'affected': services.cancel_series_service(
        user=request.user, series_id=series_id, from_index=from_index
    )}



# Transfers between companies (two linked transactions, outside the DRE)

def _transfer_out(transfer) -> dict:
    outflow, inflow = services.transfer_legs(transfer)
    return {
        'id': transfer.pk, 'date': outflow.date, 'amount': outflow.amount, 'status': outflow.status,
        'notes': outflow.notes, 'created_at': transfer.created_at,
        'from_company_id': outflow.company_id, 'from_company_name': outflow.company.name,
        'from_account_id': outflow.account_id, 'outflow_id': outflow.pk,
        'to_company_id': inflow.company_id, 'to_company_name': inflow.company.name,
        'to_account_id': inflow.account_id, 'inflow_id': inflow.pk,
    }


@router.post('/transfer', response={201: TransferOut})
@require_permission('transactions', CREATE)
def create_transfer_endpoint(request, data: CreateTransfer):
    return 201, _transfer_out(services.create_transfer_service(user=request.user, **data.dict()))


@router.get('/transfer/{transfer_id}', response=TransferOut)
@require_permission('transactions', VIEW)
def get_transfer_endpoint(request, transfer_id: int):
    return _transfer_out(services.get_transfer_service(user=request.user, transfer_id=transfer_id))


@router.patch('/transfer/{transfer_id}', response=TransferOut)
@require_permission('transactions', CHANGE)
def update_transfer_endpoint(request, transfer_id: int, data: PatchTransfer):
    transfer = services.update_transfer_service(
        user=request.user, transfer_id=transfer_id, **data.dict(exclude_unset=True)
    )
    return _transfer_out(transfer)


@router.delete('/transfer/{transfer_id}', response={204: None})
@require_permission('transactions', DELETE)
def delete_transfer_endpoint(request, transfer_id: int):
    services.delete_transfer_service(user=request.user, transfer_id=transfer_id)
    return 204, None
