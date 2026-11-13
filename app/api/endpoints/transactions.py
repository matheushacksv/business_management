from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.transactions_dto import (
    CreateTransaction,
    PatchTransaction,
    TransactionFilters,
    TransactionOut,
)
from apps.finance import services

router = Router(tags=['Transactions'])


@router.post('/transaction', response={201: TransactionOut})
def create_transaction_endpoint(request, data: CreateTransaction):
    return 201, services.create_transaction_service(user=request.user, **data.dict())


@router.get('/transaction', response=list[TransactionOut])
@paginate(PageNumberPagination, page_size=50)
def list_transactions_endpoint(request, filters: Query[TransactionFilters]):
    return services.list_transactions_service(user=request.user, **filters.dict())


@router.get('/transaction/{transaction_id}', response=TransactionOut)
def get_transaction_endpoint(request, transaction_id: int):
    return services.get_transaction_service(user=request.user, transaction_id=transaction_id)


@router.patch('/transaction/{transaction_id}', response=TransactionOut)
def update_transaction_endpoint(request, transaction_id: int, data: PatchTransaction):
    return services.update_transaction_service(
        user=request.user, transaction_id=transaction_id, **data.dict(exclude_unset=True)
    )


@router.delete('/transaction/{transaction_id}', response={204: None})
def delete_transaction_endpoint(request, transaction_id: int):
    services.delete_transaction_service(user=request.user, transaction_id=transaction_id)
    return 204, None
