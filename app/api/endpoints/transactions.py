import json

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from ninja import File, Form, Query, Router
from ninja.files import UploadedFile
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.transactions_dto import (
    BulkIds,
    BulkUpdateTransactions,
    CreateSeries,
    CreateTransaction,
    CreateTransfer,
    ImportInspectOut,
    MappedImportOut,
    PatchSeries,
    PatchTransaction,
    PatchTransfer,
    SeriesChangeOut,
    SplitTransaction,
    SeriesOut,
    StatementAnalysisOut,
    StatementCommit,
    StatementResultOut,
    TransactionFilters,
    TransactionOut,
    TransferOut,
)
from apps.finance import services
from apps.finance.exporter import XLSX_CONTENT_TYPE, transactions_xlsx
from apps.finance.mapped_import import inspect_file, run_mapped_import
from apps.finance.statement_import import analyze_statement_service, commit_statement_service
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, check_permission, require_permission

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


@router.post('/transaction/bulk-update', response=SeriesChangeOut)
@require_permission('transactions', CHANGE)
def bulk_update_transactions_endpoint(request, data: BulkUpdateTransactions):
    fields = data.dict(exclude_unset=True)
    if 'sale_id' in fields:
        check_permission(request.user, 'sales', CHANGE)
    return {'affected': services.bulk_update_transactions_service(user=request.user, **fields)}


@router.post('/transaction/bulk-delete', response=SeriesChangeOut)
@require_permission('transactions', DELETE)
def bulk_delete_transactions_endpoint(request, data: BulkIds):
    return {'affected': services.bulk_delete_transactions_service(user=request.user, ids=data.ids)}


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


@router.post('/transaction/{transaction_id}/split', response=list[TransactionOut])
@require_permission('transactions', CHANGE)
def split_transaction_endpoint(request, transaction_id: int, data: SplitTransaction):
    return services.split_transaction_service(user=request.user, transaction_id=transaction_id, **data.dict())


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


# Import from any .xlsx/.csv with column mapping (stateless: the file comes on every call)

@router.post('/transaction-import/inspect', response=ImportInspectOut)
@require_permission('transactions', CREATE)
def inspect_import_endpoint(
    request, file: File[UploadedFile], sheet: Form[str | None] = None, header_row: Form[int | None] = None,
):
    """Columns of the file (header + sample values), to build the mapping."""
    return inspect_file(file, sheet=sheet, header_row=header_row)


@router.post('/transaction-import', response=MappedImportOut)
@require_permission('transactions', CREATE)
def mapped_import_endpoint(
    request, file: File[UploadedFile], mapping: Form[str], sheet: Form[str | None] = None,
    header_row: Form[int | None] = None, commit: Form[bool] = False,
):
    """Dry run (commit=false) or import. `mapping` is JSON: columns, fixed, type_mode, value_maps..."""
    try:
        mapping_data = json.loads(mapping)
    except json.JSONDecodeError:
        raise ValidationError('mapping must be valid JSON')
    if not isinstance(mapping_data, dict):
        raise ValidationError('mapping must be a JSON object')
    return run_mapped_import(
        file, user=request.user, mapping=mapping_data, sheet=sheet, header_row=header_row, commit=commit,
    )


# Bank statement (OFX or C6 Bank PDF): analyze -> review on screen -> commit

@router.post('/statement-import/analyze', response=StatementAnalysisOut)
@require_permission('transactions', CREATE)
def analyze_statement_endpoint(request, file: File[UploadedFile], account_id: Form[int]):
    return analyze_statement_service(user=request.user, account_id=account_id, file=file)


@router.post('/statement-import', response=StatementResultOut)
@require_permission('transactions', CREATE)
def commit_statement_endpoint(request, data: StatementCommit):
    check_permission(request.user, 'transactions', CHANGE)  # settling changes planned installments
    return commit_statement_service(user=request.user, account_id=data.account_id,
                                    lines=[line.dict() for line in data.lines])
