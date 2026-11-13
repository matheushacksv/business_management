from typing import List

from ninja import Router

from api.schemas.companies_dto import CompanyCreateDTO, CompanyOut, CompanyUpdateDTO
from apps.companies import services
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Companies'])


@router.get('/company', response=List[CompanyOut])
@require_permission('companies', VIEW)
def list_company_endpoint(request):
    return 200, services.list_companies_service(request.user)


@router.post('/company', response={201: CompanyOut})
@require_permission('companies', CREATE)
def create_company_endpoint(request, data: CompanyCreateDTO):
    return 201, services.create_company_service(
        user=request.user, name=data.name, 
        cnpj=data.cnpj, initial_balance=data.initial_balance
    )


@router.get('/company/{company_id}', response=CompanyOut)
@require_permission('companies', VIEW)
def get_company_endpoint(request, company_id: int):
    return 200, services.get_company_service(user=request.user, company_id=company_id)


@router.patch('/company/{company_id}', response=CompanyOut)
@require_permission('companies', CHANGE)
def update_company_endpoint(request, company_id: int, data: CompanyUpdateDTO):
    return 200, services.update_company_service(
        user=request.user, company_id=company_id, **data.dict(exclude_unset=True)
    )


@router.delete('/company/{company_id}', response={204: None})
@require_permission('companies', DELETE)
def delete_company_endpoint(request, company_id: int):
    return 204, services.delete_company_service(
        user=request.user, company_id=company_id
    )
