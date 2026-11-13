from ninja import Router

from api.schemas.accounts_dto import AccountOut, CreateAccount, PatchAccount
from apps.finance import services
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Accounts'])


@router.post('/account', response={201: AccountOut})
@require_permission('accounts', CREATE)
def create_account_endpoint(request, data: CreateAccount):
    return 201, services.create_account_service(
        user=request.user, company_id=data.company_id, name=data.name
    )


@router.get('/account', response=list[AccountOut])
@require_permission('accounts', VIEW)
def list_accounts_endpoint(request, company_id: int | None = None):
    return services.list_accounts_service(user=request.user, company_id=company_id)


@router.get('/account/{account_id}', response=AccountOut)
@require_permission('accounts', VIEW)
def get_account_endpoint(request, account_id: int):
    return services.get_account_service(user=request.user, account_id=account_id)


@router.patch('/account/{account_id}', response=AccountOut)
@require_permission('accounts', CHANGE)
def update_account_endpoint(request, account_id: int, data: PatchAccount):
    return services.update_account_service(
        user=request.user, account_id=account_id, name=data.name
    )


@router.delete('/account/{account_id}', response={204: None})
@require_permission('accounts', DELETE)
def delete_account_endpoint(request, account_id: int):
    services.delete_account_service(user=request.user, account_id=account_id)
    return 204, None
